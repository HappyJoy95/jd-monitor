# 京东订单池 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an atomically written local JSON order pool keyed by `orderId`, preserving the first capture time and the latest complete raw order object, then refresh it automatically after each successful capture.

**Architecture:** `order_pool.py` owns raw JSONL parsing, validation, latest-order replacement, and atomic JSON writing. The CLI exposes a standalone rebuild command and coordinates automatic rebuilding after capture; the existing capture module remains responsible only for HTTP requests and immutable raw JSONL persistence.

**Tech Stack:** Python 3.12 standard library (`json`, `datetime`, `tempfile`, `os`, `pathlib`, `dataclasses`), requests, pytest.

---

## File structure

- Create `jd_monitor/order_pool.py`: validate raw records, build the keyed pool, and atomically replace the output file.
- Create `tests/test_order_pool.py`: pool semantics, validation, and safe-write tests with synthetic data.
- Modify `jd_monitor/__main__.py`: reusable parser, standalone `pool` command, and post-capture refresh.
- Create `tests/test_cli.py`: privacy-safe CLI output and command orchestration tests.
- Modify `tests/test_capture.py`: update the existing capture CLI test for automatic pool refresh.
- Modify `README.md`: document the pool format, rebuild command, and automatic refresh.

### Task 1: Build and atomically persist the order pool

**Files:**
- Create: `jd_monitor/order_pool.py`
- Create: `tests/test_order_pool.py`

- [ ] **Step 1: Write failing tests for latest replacement and first-seen preservation**

```python
import json
from pathlib import Path

from jd_monitor.order_pool import build_order_pool


def write_raw(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def raw_record(captured_at: str, orders: list[object]) -> dict:
    return {
        "captured_at": captured_at,
        "request": {"page_no": 1},
        "response": {
            "code": "0",
            "result": {
                "newOrderinfoMains": {
                    "resultList": orders,
                }
            },
        },
    }


def test_build_pool_keeps_first_seen_and_latest_complete_order(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "order_pool.json"
    write_raw(raw_path, [
        raw_record(
            "2026-07-29T10:00:00+08:00",
            [{"orderId": "1001", "status": "old", "oldOnly": True}],
        ),
        raw_record(
            "2026-07-29T11:00:00+08:00",
            [
                {"orderId": "1001", "status": "new"},
                {"orderId": 1002, "status": "first"},
            ],
        ),
    ])

    result = build_order_pool(raw_path, pool_path)
    pool = json.loads(pool_path.read_text(encoding="utf-8"))

    assert (result.raw_records, result.unique_orders) == (2, 2)
    assert pool["1001"] == {
        "first_seen_at": "2026-07-29T10:00:00+08:00",
        "order": {"orderId": "1001", "status": "new"},
    }
    assert pool["1002"]["first_seen_at"] == "2026-07-29T11:00:00+08:00"
    assert pool["1002"]["order"] == {"orderId": 1002, "status": "first"}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_order_pool.py::test_build_pool_keeps_first_seen_and_latest_complete_order -q
```

Expected: collection fails because `jd_monitor.order_pool` does not exist.

- [ ] **Step 3: Implement parsing, replacement, and atomic writing**

Create `jd_monitor/order_pool.py`:

```python
"""Build a latest-value order pool from immutable raw capture records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile


class OrderPoolError(RuntimeError):
    """Raised when an order pool cannot be safely rebuilt."""


@dataclass(frozen=True)
class PoolBuildResult:
    raw_records: int
    unique_orders: int
    output_path: Path


def _validate_captured_at(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrderPoolError("原始记录缺少采集时间")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OrderPoolError("原始记录采集时间无效") from exc
    if parsed.tzinfo is None:
        raise OrderPoolError("原始记录采集时间缺少时区")
    return value


def _orders_from_record(record: object) -> list[object]:
    if not isinstance(record, dict):
        raise OrderPoolError("原始记录格式无效")
    response = record.get("response")
    if not isinstance(response, dict):
        return []
    result = response.get("result")
    if not isinstance(result, dict):
        return []
    main = result.get("newOrderinfoMains")
    if not isinstance(main, dict):
        return []
    orders = main.get("resultList", [])
    if orders is None:
        return []
    if not isinstance(orders, list):
        raise OrderPoolError("订单列表格式无效")
    return orders


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                value,
                output,
                ensure_ascii=False,
                indent=2,
                separators=(",", ": "),
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    except (OSError, TypeError, ValueError) as exc:
        raise OrderPoolError("订单池写入失败") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def build_order_pool(
    raw_path: Path | str,
    output_path: Path | str,
) -> PoolBuildResult:
    source = Path(raw_path)
    target = Path(output_path)
    pool: dict[str, object] = {}
    raw_records = 0

    try:
        with source.open(encoding="utf-8") as raw_file:
            for line_number, line in enumerate(raw_file, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise OrderPoolError(
                        f"原始日志第 {line_number} 行不是有效 JSON"
                    ) from exc
                captured_at = _validate_captured_at(
                    record.get("captured_at")
                    if isinstance(record, dict)
                    else None
                )
                raw_records += 1
                for order in _orders_from_record(record):
                    if not isinstance(order, dict):
                        raise OrderPoolError("订单列表包含非对象元素")
                    order_id = str(order.get("orderId") or "").strip()
                    if not order_id:
                        raise OrderPoolError("订单缺少订单号")
                    if order_id not in pool:
                        pool[order_id] = {
                            "first_seen_at": captured_at,
                            "order": order,
                        }
                    else:
                        pool[order_id]["order"] = order
    except OSError as exc:
        raise OrderPoolError("无法读取原始订单日志") from exc

    _atomic_write_json(target, pool)
    return PoolBuildResult(
        raw_records=raw_records,
        unique_orders=len(pool),
        output_path=target,
    )
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_order_pool.py::test_build_pool_keeps_first_seen_and_latest_complete_order -q
```

Expected: `1 passed`.

- [ ] **Step 5: Add failing validation and non-overwrite tests**

Append to `tests/test_order_pool.py`:

```python
import pytest

from jd_monitor.order_pool import OrderPoolError


@pytest.mark.parametrize(
    "line",
    [
        "not-json\n",
        json.dumps(raw_record("", [{"orderId": "1"}])) + "\n",
        json.dumps(raw_record(
            "2026-07-29T10:00:00",
            [{"orderId": "1"}],
        )) + "\n",
        json.dumps(raw_record(
            "2026-07-29T10:00:00+08:00",
            ["not-an-object"],
        )) + "\n",
        json.dumps(raw_record(
            "2026-07-29T10:00:00+08:00",
            [{"status": "missing-id"}],
        )) + "\n",
    ],
)
def test_invalid_raw_data_does_not_replace_existing_pool(tmp_path, line):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "order_pool.json"
    raw_path.write_text(line, encoding="utf-8")
    pool_path.write_text('{"existing":true}\n', encoding="utf-8")

    with pytest.raises(OrderPoolError):
        build_order_pool(raw_path, pool_path)

    assert pool_path.read_text(encoding="utf-8") == '{"existing":true}\n'


def test_rebuilding_the_same_log_is_deterministic(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "order_pool.json"
    write_raw(raw_path, [
        raw_record(
            "2026-07-29T10:00:00+08:00",
            [{"orderId": "1", "value": "full"}],
        )
    ])

    build_order_pool(raw_path, pool_path)
    first = pool_path.read_bytes()
    build_order_pool(raw_path, pool_path)

    assert pool_path.read_bytes() == first
    assert list(tmp_path.glob(".order_pool.json.*.tmp")) == []
```

- [ ] **Step 6: Run all pool tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_order_pool.py -q
```

Expected: all pool tests pass.

- [ ] **Step 7: Commit**

```bash
git add jd_monitor/order_pool.py tests/test_order_pool.py
git commit -m "feat: build atomic raw order pool"
```

### Task 2: Add the standalone pool rebuild command

**Files:**
- Modify: `jd_monitor/__main__.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing parser and standalone command tests**

Create `tests/test_cli.py`:

```python
from pathlib import Path

from jd_monitor.__main__ import build_parser, main
from jd_monitor.order_pool import PoolBuildResult


def test_pool_command_has_local_default_paths():
    args = build_parser().parse_args(["pool"])
    assert args.command == "pool"
    assert args.input == Path("data/raw_order_responses.jsonl")
    assert args.output == Path("data/order_pool.json")


def test_pool_command_prints_counts_and_path_only(monkeypatch, capsys, tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "pool.json"

    def fake_build(source, target):
        assert source == raw_path
        assert target == pool_path
        return PoolBuildResult(7, 3, pool_path)

    monkeypatch.setattr("jd_monitor.__main__.build_order_pool", fake_build)

    exit_code = main([
        "pool",
        "--input", str(raw_path),
        "--output", str(pool_path),
    ])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        f"订单池完成：读取 7 条原始记录，汇总 3 笔订单，"
        f"已写入 {pool_path}。\n"
    )
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -q
```

Expected: collection fails because `build_parser` is not exported.

- [ ] **Step 3: Refactor the parser and implement `pool`**

Replace `jd_monitor/__main__.py` with:

```python
"""Command-line entry points for raw order capture and pool rebuilding."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .capture import CaptureError, OrderCapture, session_from_cookie_file
from .order_pool import OrderPoolError, build_order_pool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="采集京东到家订单原始响应并维护订单池"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="执行一次原始订单采集")
    capture.add_argument(
        "--cookies", type=Path, default=Path("data/cookies.json")
    )
    capture.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw_order_responses.jsonl"),
    )
    capture.add_argument("--pool", type=Path)

    pool = commands.add_parser("pool", help="从原始日志重建订单池")
    pool.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw_order_responses.jsonl"),
    )
    pool.add_argument(
        "--output",
        type=Path,
        default=Path("data/order_pool.json"),
    )
    return parser


def _run_pool(args: argparse.Namespace) -> int:
    result = build_order_pool(args.input, args.output)
    print(
        f"订单池完成：读取 {result.raw_records} 条原始记录，"
        f"汇总 {result.unique_orders} 笔订单，"
        f"已写入 {result.output_path}。"
    )
    return 0


def _run_capture(args: argparse.Namespace) -> int:
    session = session_from_cookie_file(args.cookies)
    result = OrderCapture(session, args.output).capture_once()
    print(f"采集完成：{result.pages} 页，{result.responses} 个响应。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            return _run_capture(args)
        if args.command == "pool":
            return _run_pool(args)
    except CaptureError:
        print(
            "采集失败：请检查登录状态、Cookie 文件和网络连接。",
            file=sys.stderr,
        )
        return 1
    except OrderPoolError:
        print(
            "订单池更新失败：请检查原始日志格式和输出目录。",
            file=sys.stderr,
        )
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/__main__.py tests/test_cli.py
git commit -m "feat: add order pool rebuild command"
```

### Task 3: Refresh the pool after every successful capture

**Files:**
- Modify: `jd_monitor/__main__.py`
- Modify: `tests/test_capture.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Replace the existing capture CLI test with a failing auto-refresh test**

Replace `test_main_capture_reports_counts_without_response_or_cookie_content` in `tests/test_capture.py` with:

```python
def test_main_capture_refreshes_pool_and_reports_counts_only(
    monkeypatch, capsys, tmp_path: Path
):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "custom_pool.json"
    calls = []

    class FakeCapture:
        def __init__(self, session, output_path):
            assert session is not None
            assert output_path == raw_path

        def capture_once(self):
            calls.append("capture")

            class Result:
                pages = 2
                responses = 2

            return Result()

    def fake_build(source, target):
        calls.append(("pool", source, target))
        return PoolBuildResult(8, 5, target)

    monkeypatch.setattr(
        "jd_monitor.__main__.session_from_cookie_file",
        lambda _: object(),
    )
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)
    monkeypatch.setattr("jd_monitor.__main__.build_order_pool", fake_build)

    exit_code = main([
        "capture",
        "--cookies", str(tmp_path / "cookies.json"),
        "--output", str(raw_path),
        "--pool", str(pool_path),
    ])

    assert exit_code == 0
    assert calls == ["capture", ("pool", raw_path, pool_path)]
    assert capsys.readouterr().out == (
        f"采集完成：2 页，2 个响应；"
        f"订单池 5 笔，已写入 {pool_path}。\n"
    )
```

Add these imports to `tests/test_capture.py`:

```python
from jd_monitor.order_pool import PoolBuildResult
```

- [ ] **Step 2: Add a failing default derived pool-path test**

Append to `tests/test_cli.py`:

```python
def test_capture_pool_defaults_to_raw_file_directory():
    args = build_parser().parse_args([
        "capture",
        "--output",
        "/private/data/custom_raw.jsonl",
    ])

    assert args.pool is None
    assert args.output.with_name("order_pool.json") == Path(
        "/private/data/order_pool.json"
    )
```

- [ ] **Step 3: Run the capture and CLI tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_capture.py tests/test_cli.py -q
```

Expected: the auto-refresh test fails because `_run_capture` does not call `build_order_pool`.

- [ ] **Step 4: Implement post-capture pool rebuilding**

Replace `_run_capture` in `jd_monitor/__main__.py` with:

```python
def _run_capture(args: argparse.Namespace) -> int:
    session = session_from_cookie_file(args.cookies)
    result = OrderCapture(session, args.output).capture_once()
    pool_path = args.pool or args.output.with_name("order_pool.json")
    try:
        pool_result = build_order_pool(args.output, pool_path)
    except OrderPoolError:
        print(
            "采集已保存，但订单池更新失败："
            "请检查原始日志格式和输出目录。",
            file=sys.stderr,
        )
        return 1
    print(
        f"采集完成：{result.pages} 页，{result.responses} 个响应；"
        f"订单池 {pool_result.unique_orders} 笔，"
        f"已写入 {pool_result.output_path}。"
    )
    return 0
```

Keep the outer `OrderPoolError` handler for the standalone `pool` command. The nested handler gives capture users an accurate message that raw persistence already succeeded.

- [ ] **Step 5: Run capture and CLI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_capture.py tests/test_cli.py -q
```

Expected: all capture and CLI tests pass.

- [ ] **Step 6: Commit**

```bash
git add jd_monitor/__main__.py tests/test_capture.py tests/test_cli.py
git commit -m "feat: refresh order pool after capture"
```

### Task 4: Document and verify the complete workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add order-pool documentation**

Append this section to `README.md`:

````markdown
## 订单池

每次采集完成后，程序会从完整原始日志重建同目录下的 `order_pool.json`。订单号是顶层键，每个条目包含：

- `first_seen_at`：订单第一次出现在原始日志中的具体时间；
- `order`：该订单最新一次出现时的完整京东原始对象。

相同订单后续出现时会完整覆盖 `order`，但不会改变 `first_seen_at`。

只重建订单池、不请求京东接口：

```bash
python -m jd_monitor pool
```

显式指定文件：

```bash
python -m jd_monitor pool \
  --input data/raw_order_responses.jsonl \
  --output data/order_pool.json
```

订单池包含完整客户与订单信息，只能保存在本机，不得提交或发送。
````

- [ ] **Step 2: Run the full automated verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q jd_monitor
git diff --check
```

Expected: all tests pass, compilation succeeds, and `git diff --check` prints nothing.

- [ ] **Step 3: Rebuild the real local pool**

Run:

```bash
.venv/bin/python -m jd_monitor pool
```

Expected: the command reports the number of raw records and unique orders without printing any order ID or order content.

- [ ] **Step 4: Validate the real pool without exposing private data**

Run:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

pool_path = Path("data/order_pool.json")
pool = json.loads(pool_path.read_text(encoding="utf-8"))
valid = all(
    isinstance(order_id, str)
    and isinstance(entry, dict)
    and isinstance(entry.get("first_seen_at"), str)
    and isinstance(entry.get("order"), dict)
    and str(entry["order"].get("orderId")) == order_id
    for order_id, entry in pool.items()
)
print({
    "orders": len(pool),
    "structure_valid": valid,
    "bytes": pool_path.stat().st_size,
})
PY
```

Expected: `structure_valid` is `True`; output contains counts only.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: explain raw order pool"
```

## Final verification

- [ ] Run `.venv/bin/python -m pytest -q`.
- [ ] Run `.venv/bin/python -m compileall -q jd_monitor`.
- [ ] Run `git diff --check`.
- [ ] Confirm `git status --short` contains no unintended files.
- [ ] Run `.venv/bin/python -m jd_monitor pool`.
- [ ] Confirm `data/order_pool.json` is ignored by Git.
- [ ] Confirm every pool key equals `str(entry["order"]["orderId"])`.
- [ ] Confirm each `first_seen_at` is the earliest `captured_at` for that order in the raw JSONL.
- [ ] Confirm the command output contains no order IDs, order content, customer data, or Cookie values.
