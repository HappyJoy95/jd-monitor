# 京东订单状态判定与页面差分验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the current Jingdong order-page status rules locally, read the status text rendered by the real page, and append privacy-safe per-order comparison results for multi-day verification.

**Architecture:** `jd_status.py` is a pure rule engine over raw order dictionaries. `page_verifier.py` uses Playwright only as a black-box reader of the final DOM, while `verification.py` compares both sources and appends bounded status-only JSONL records. The CLI coordinates one-shot and interval modes without allowing browser failures to affect raw API persistence.

**Tech Stack:** Python 3.12, dataclasses, requests, Playwright, pytest, JSON Lines.

---

## File structure

- `jd_monitor/jd_status.py`: pure Jingdong status rules and traceable result model.
- `jd_monitor/page_verifier.py`: browser lifecycle, page filters, DOM extraction, and pagination.
- `jd_monitor/verification.py`: flatten captured orders, compare local/page statuses, and append safe logs.
- `jd_monitor/capture.py`: return captured payloads in memory in addition to writing raw JSONL.
- `jd_monitor/__main__.py`: add `verify` one-shot and interval commands.
- `tests/test_jd_status.py`: exhaustive status branch, unknown, and conflict tests.
- `tests/test_page_verifier.py`: DOM extraction normalization and page structure tests without live Jingdong access.
- `tests/test_verification.py`: comparison, privacy, and JSONL persistence tests.
- `tests/test_cli.py`: one-shot/interval CLI orchestration tests with fake services.
- `README.md`: browser dependency, login-cookie, one-shot, loop, and log review instructions.
- `pyproject.toml`: add Playwright runtime dependency.

### Task 1: Implement the traceable status result and top-level overrides

**Files:**
- Create: `jd_monitor/jd_status.py`
- Create: `tests/test_jd_status.py`

- [ ] **Step 1: Write failing tests for server-title, prescription, and base statuses**

```python
import pytest

from jd_monitor.jd_status import resolve_jd_status


def test_server_title_overrides_every_local_rule():
    result = resolve_jd_status({
        "sendOrderCard": {"orderStatusTitle": "服务端状态"},
        "stationOrderStatus": 6,
    })
    assert (result.text, result.rule_id, result.source) == (
        "服务端状态", "server_order_status_title", "server_title"
    )


@pytest.mark.parametrize("prescription, expected, rule_id", [
    ({"useDrugName": "处方"}, "处方单待审核", "prescription_review"),
    ({"picUrlList": ["image"]}, "处方单待审核", "prescription_review"),
    ({}, "待接单", "waiting_accept"),
])
def test_station_status_16_uses_prescription_data(prescription, expected, rule_id):
    result = resolve_jd_status({
        "stationOrderStatus": 16,
        "newOrderinfoExtend": {"prescriptionDTO": prescription},
    })
    assert (result.text, result.rule_id) == (expected, rule_id)


@pytest.mark.parametrize("code, expected, rule_id", [
    (4, "配送中", "delivering"),
    (-4, "已取消", "cancelled"),
    (6, "已完成", "completed"),
    (-3, "待审核", "waiting_audit"),
    (30, "商品已送达", "goods_delivered"),
])
def test_base_statuses_match_jingdong(code, expected, rule_id):
    result = resolve_jd_status({"stationOrderStatus": code})
    assert (result.text, result.rule_id) == (expected, rule_id)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_jd_status.py -q`

Expected: FAIL because `jd_monitor.jd_status` does not exist.

- [ ] **Step 3: Implement the result model and these rules**

```python
from dataclasses import dataclass, field

RULESET_VERSION = "pick_assistant-2026-07-29"
STATUS_FIELD_NAMES = (
    "stationOrderStatus", "printMark", "pickMark", "grabMark",
    "businessType", "carrierNo", "businessTag",
)


@dataclass(frozen=True)
class JdStatus:
    text: str
    rule_id: str
    source: str
    matched_fields: dict[str, object]
    ruleset_version: str = RULESET_VERSION
    matched_rule_ids: tuple[str, ...] = field(default_factory=tuple)


def _fields(order):
    return {name: order.get(name) for name in STATUS_FIELD_NAMES}


def _result(order, text, rule_id, source="local_rule", matched=()):
    return JdStatus(text, rule_id, source, _fields(order), matched_rule_ids=tuple(matched))


def resolve_jd_status(order):
    card = order.get("sendOrderCard") or {}
    title = card.get("orderStatusTitle")
    if isinstance(title, str) and title.strip():
        return _result(order, title.strip(), "server_order_status_title", "server_title")

    station_status = order.get("stationOrderStatus")
    if station_status == 16:
        extension = order.get("newOrderinfoExtend") or {}
        prescription = extension.get("prescriptionDTO") or {}
        has_prescription = bool(
            prescription.get("useDrugName") or prescription.get("picUrlList")
        )
        return _result(
            order,
            "处方单待审核" if has_prescription else "待接单",
            "prescription_review" if has_prescription else "waiting_accept",
        )

    base = {
        4: ("配送中", "delivering"),
        -4: ("已取消", "cancelled"),
        6: ("已完成", "completed"),
        -3: ("待审核", "waiting_audit"),
        30: ("商品已送达", "goods_delivered"),
    }
    if station_status in base:
        text, rule_id = base[station_status]
        return _result(order, text, rule_id)
    return _resolve_active_status(order)


def _resolve_active_status(order):
    return _result(order, "京东未知状态", "unknown", "unknown")
```

Task 2 replaces the temporary `_resolve_active_status` implementation with the complete active-order rules.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_jd_status.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/jd_status.py tests/test_jd_status.py
git commit -m "feat: add JD base status resolver"
```

### Task 2: Complete active-order rules, self-pickup, unknown, and conflicts

**Files:**
- Modify: `jd_monitor/jd_status.py`
- Modify: `tests/test_jd_status.py`

- [ ] **Step 1: Add failing parameterized tests for every active branch**

```python
@pytest.mark.parametrize("extra, expected, rule_id", [
    ({"printMark": 1, "pickMark": 1, "grabMark": 1, "businessType": 1}, "待打印", "waiting_print"),
    ({"printMark": 2, "pickMark": 1, "grabMark": 1, "businessType": 1}, "待拣货", "waiting_pick"),
    ({"pickMark": 2, "grabMark": 1}, "待抢单", "waiting_grab"),
    ({"pickMark": 2, "grabMark": 2}, "已抢单", "grabbed"),
    ({"pickMark": 2, "grabMark": 3}, "已收单", "received"),
    ({"pickMark": 2, "grabMark": 4}, "已完成", "grab_completed"),
    ({"pickMark": 2, "grabMark": 5}, "取消", "grab_cancelled"),
    ({"pickMark": 2, "grabMark": 6}, "取货失败", "pickup_failed"),
    ({"pickMark": 2, "grabMark": 7}, "取货失败待审核", "pickup_failed_audit"),
    ({"pickMark": 2, "grabMark": 8}, "撤销抢单", "grab_revoked"),
    ({"pickMark": 2, "grabMark": 10}, "投递失败", "delivery_failed"),
    ({"businessType": 8}, "待核验", "waiting_verification"),
    ({"carrierNo": 1130, "grabMark": 0}, "召唤配送失败", "summon_failed"),
    ({"carrierNo": 1130, "pickMark": 2, "grabMark": None}, "即将召唤配送", "summon_pending"),
])
def test_active_status_rules(extra, expected, rule_id):
    order = {"stationOrderStatus": 1, **extra}
    result = resolve_jd_status(order)
    assert (result.text, result.rule_id) == (expected, rule_id)


@pytest.mark.parametrize("carrier", [9999, "9999"])
def test_self_pickup_accepts_numeric_and_string_carrier(carrier):
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "carrierNo": carrier,
        "businessTag": "normal",
        "pickMark": 2,
        "grabMark": -1,
    })
    assert (result.text, result.rule_id) == ("待自提", "waiting_self_pickup")


def test_a13_business_tag_excludes_self_pickup():
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "carrierNo": 9999,
        "businessTag": "prefix-A13-suffix",
        "pickMark": 2,
        "grabMark": -1,
    })
    assert result.source == "unknown"


def test_multiple_matches_are_reported_as_conflict():
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "printMark": 2,
        "pickMark": 1,
        "grabMark": 1,
        "businessType": 8,
    })
    assert result.source == "conflict"
    assert result.text == "京东状态规则冲突"
    assert set(result.matched_rule_ids) == {"waiting_pick", "waiting_verification"}
```

- [ ] **Step 2: Run active-rule tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_jd_status.py -q`

Expected: FAIL because active-order rules are not implemented.

- [ ] **Step 3: Implement ordered rule collection without guessing conflicts**

```python
def is_self_pickup(order):
    business_tag = order.get("businessTag") or ""
    return str(order.get("carrierNo")) == "9999" and "A13" not in business_tag


def _resolve_active_status(order):
    if order.get("stationOrderStatus") not in (1, 20):
        return _result(order, "京东未知状态", "unknown", "unknown")

    matches = []
    add = lambda condition, text, rule_id: matches.append((text, rule_id)) if condition else None
    print_mark = order.get("printMark")
    pick_mark = order.get("pickMark")
    grab_mark = order.get("grabMark")
    business_type = order.get("businessType")
    carrier = str(order.get("carrierNo"))

    add(print_mark == 1 and pick_mark == 1 and grab_mark != 0 and business_type not in (8, 9), "待打印", "waiting_print")
    add(isinstance(print_mark, (int, float)) and print_mark > 1 and pick_mark == 1 and grab_mark != 0, "待拣货", "waiting_pick")
    grab_map = {
        1: ("待抢单", "waiting_grab"), 2: ("已抢单", "grabbed"),
        3: ("已收单", "received"), 4: ("已完成", "grab_completed"),
        5: ("取消", "grab_cancelled"), 6: ("取货失败", "pickup_failed"),
        7: ("取货失败待审核", "pickup_failed_audit"), 8: ("撤销抢单", "grab_revoked"),
        10: ("投递失败", "delivery_failed"),
    }
    if pick_mark == 2 and grab_mark in grab_map:
        matches.append(grab_map[grab_mark])
    add(business_type == 8, "待核验", "waiting_verification")
    add(is_self_pickup(order) and pick_mark == 2 and grab_mark != 0, "待自提", "waiting_self_pickup")
    add(carrier == "1130" and grab_mark == 0, "召唤配送失败", "summon_failed")
    add(carrier == "1130" and pick_mark == 2 and grab_mark is None, "即将召唤配送", "summon_pending")

    if not matches:
        return _result(order, "京东未知状态", "unknown", "unknown")
    if len(matches) > 1:
        return _result(order, "京东状态规则冲突", "conflict", "conflict", [rule for _, rule in matches])
    text, rule_id = matches[0]
    return _result(order, text, rule_id)
```

- [ ] **Step 4: Run all status tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_jd_status.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/jd_status.py tests/test_jd_status.py
git commit -m "feat: complete JD active status rules"
```

### Task 3: Expose captured payloads safely for same-run verification

**Files:**
- Modify: `jd_monitor/capture.py`
- Modify: `tests/test_capture.py`

- [ ] **Step 1: Write a failing test that the capture result carries in-memory payloads**

```python
def test_capture_result_returns_payloads_without_changing_jsonl(tmp_path):
    payload = {"code": "0", "result": {"newOrderinfoMains": {"totalCount": 0, "resultList": []}}}

    class Response:
        status_code = 200

        def json(self):
            return payload

    class Session:
        def get(self, url, *, params, timeout):
            return Response()

    session = Session()
    result = OrderCapture(session, tmp_path / "raw.jsonl").capture_once(
        now=datetime(2026, 7, 29, 13, 44, 53)
    )
    assert result.payloads == (payload,)
    assert "payloads" not in (tmp_path / "raw.jsonl").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capture.py::test_capture_result_returns_payloads_without_changing_jsonl -q`

Expected: FAIL because `CaptureResult` has no `payloads`.

- [ ] **Step 3: Add a repr-safe payload tuple to `CaptureResult`**

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class CaptureResult:
    pages: int
    responses: int
    payloads: tuple[object, ...] = field(default_factory=tuple, repr=False)
```

Collect payloads only after `_append_record` succeeds, so the returned tuple and the raw JSONL always describe the same pages:

```python
def capture_once(self, now: datetime | None = None) -> CaptureResult:
    captured_at = self._as_shanghai(now)
    first_request = self._request_metadata(captured_at, page_no=1)
    first_payload = self._fetch(first_request)
    page_count = self._page_count(first_payload, first_request["page_size"])
    self._append_record(captured_at, first_request, first_payload)
    payloads = [first_payload]

    for page_no in range(2, page_count + 1):
        request = self._request_metadata(captured_at, page_no=page_no)
        payload = self._fetch(request)
        self._append_record(captured_at, request, payload)
        payloads.append(payload)
    return CaptureResult(
        pages=page_count,
        responses=len(payloads),
        payloads=tuple(payloads),
    )
```

Do not serialize `payloads` into summaries or CLI output.

- [ ] **Step 4: Run capture tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_capture.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/capture.py tests/test_capture.py
git commit -m "feat: expose captured payloads for verification"
```

### Task 4: Implement the black-box page status collector

**Files:**
- Create: `jd_monitor/page_verifier.py`
- Create: `tests/test_page_verifier.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests for normalized DOM records and structural errors**

```python
import pytest

from jd_monitor.page_verifier import PageStructureError, normalize_dom_records


def test_normalize_dom_records_returns_one_status_per_order():
    result = normalize_dom_records([
        {"orderId": "1001", "statuses": [" 待拣货 "]},
        {"orderId": "1002", "statuses": ["已完成"]},
    ])
    assert result == {"1001": "待拣货", "1002": "已完成"}


@pytest.mark.parametrize("record", [
    {"orderId": "", "statuses": ["待拣货"]},
    {"orderId": "1001", "statuses": []},
    {"orderId": "1001", "statuses": ["待拣货", "待核验"]},
])
def test_normalize_dom_records_rejects_ambiguous_cards(record):
    with pytest.raises(PageStructureError):
        normalize_dom_records([record])
```

- [ ] **Step 2: Run page tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_page_verifier.py -q`

Expected: FAIL because `jd_monitor.page_verifier` does not exist.

- [ ] **Step 3: Implement Playwright lifecycle and DOM extraction**

```python
PAGE_URL = "https://order.jddj.com/static/web/html/pick_assistant.html"
EXTRACT_CARDS = """() => Array.from(document.querySelectorAll('#content-pick-box1 .content-box-checkbox')).map(card => {
  const info = Array.from(card.querySelectorAll('p.comment')).find(p => p.textContent.includes('订单编号：'));
  const orderId = info?.querySelector('a')?.textContent?.trim() || '';
  const statuses = Array.from(card.querySelectorAll('.title .time.redColor'))
    .filter(node => node.offsetParent !== null)
    .map(node => node.textContent.trim())
    .filter(Boolean);
  return {orderId, statuses};
})"""


class PageStructureError(RuntimeError):
    """Raised when the rendered order page cannot be read unambiguously."""


def normalize_dom_records(records):
    output = {}
    for record in records:
        order_id = str(record.get("orderId") or "").strip()
        statuses = [str(value).strip() for value in record.get("statuses", []) if str(value).strip()]
        if not order_id or len(statuses) != 1:
            raise PageStructureError("订单卡片状态结构异常")
        output[order_id] = statuses[0]
    return output
```

Add `JdOrderPage` as an async context manager. It launches visible Chromium, loads the Playwright cookie list, opens `PAGE_URL`, waits for `#content-pick-box1`, fills `dateTimeStart`, `dateTimeEnd`, `dateTimeStarts`, and `dateTimeEnds`, clicks the visible “筛选” action, then calls `page.evaluate(EXTRACT_CARDS)` on every page. Click `.pagination .page-next:not(.disabled)` until disabled and wait for the first order ID to change after each click. Raise `PageStructureError` on login redirects, missing roots, duplicate order IDs, timeouts, or card ambiguity. Add `playwright>=1.54` to dependencies.

- [ ] **Step 4: Run page tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_page_verifier.py -q`

Expected: PASS without accessing the network or launching Chromium.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/page_verifier.py tests/test_page_verifier.py pyproject.toml
git commit -m "feat: read JD statuses from rendered page"
```

### Task 5: Compare statuses and append privacy-safe verification logs

**Files:**
- Create: `jd_monitor/verification.py`
- Create: `tests/test_verification.py`

- [ ] **Step 1: Write failing comparison and privacy tests**

```python
import json
from datetime import datetime

from jd_monitor.verification import compare_and_append


def test_compare_and_append_records_match_mismatch_and_missing_without_pii(tmp_path):
    orders = [
        {"orderId": "1", "stationOrderStatus": 6, "fullname": "secret-name"},
        {"orderId": "2", "stationOrderStatus": 4, "mobile": "secret-phone"},
        {"orderId": "3", "stationOrderStatus": 30, "fullAddress": "secret-address"},
    ]
    output = tmp_path / "verification.jsonl"

    summary = compare_and_append(
        orders,
        {"1": "已完成", "2": "已完成"},
        output,
        verified_at=datetime(2026, 7, 29, 15, 0, 0),
    )

    assert (summary.matched, summary.mismatched, summary.missing_on_page) == (1, 1, 1)
    text = output.read_text(encoding="utf-8")
    assert "secret-name" not in text
    assert "secret-phone" not in text
    assert "secret-address" not in text
    assert [json.loads(line)["result"] for line in text.splitlines()] == [
        "matched", "mismatched", "missing_on_page"
    ]
```

- [ ] **Step 2: Run comparison tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_verification.py -q`

Expected: FAIL because `jd_monitor.verification` does not exist.

- [ ] **Step 3: Implement flattening, comparison, and JSONL writing**

```python
@dataclass(frozen=True)
class VerificationSummary:
    total: int
    matched: int
    mismatched: int
    missing_on_page: int
    local_unknown: int
    local_conflict: int


def orders_from_payloads(payloads):
    orders = []
    for payload in payloads:
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        main = result.get("newOrderinfoMains", {})
        orders.extend(main.get("resultList", []) or [])
    return orders
```

`compare_and_append` resolves each order with `resolve_jd_status`, chooses `local_unknown`/`local_conflict` before page comparison, writes only the fields declared in `JdStatus.matched_fields`, and appends compact UTF-8 JSON Lines. It must never serialize the raw order or an exception containing cookie values.

- [ ] **Step 4: Run verification tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_verification.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/verification.py tests/test_verification.py
git commit -m "feat: log JD status verification results"
```

### Task 6: Add one-shot and interval verification commands

**Files:**
- Modify: `jd_monitor/__main__.py`
- Create: `tests/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests for one-shot and positive interval validation**

```python
import pytest

from jd_monitor.__main__ import build_parser


def test_verify_command_defaults_to_one_shot():
    args = build_parser().parse_args(["verify"])
    assert args.command == "verify"
    assert args.interval is None


def test_verify_interval_must_be_positive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["verify", "--interval", "0"])
```

Add an async orchestration test with fake `OrderCapture`, `JdOrderPage`, and log writer. Assert a one-shot call captures once, reads the page once, writes once, prints counts only, and never prints order or cookie content.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`

Expected: FAIL because `build_parser` and `verify` do not exist.

- [ ] **Step 3: Implement CLI orchestration and safe loop behavior**

```python
def positive_seconds(value):
    seconds = int(value)
    if seconds < 1:
        raise argparse.ArgumentTypeError("interval must be positive")
    return seconds


def build_parser():
    parser = argparse.ArgumentParser(description="采集并验证京东订单状态")
    commands = parser.add_subparsers(dest="command", required=True)
    # existing capture parser
    verify = commands.add_parser("verify", help="对照京东页面验证本地状态")
    verify.add_argument("--cookies", type=Path, default=Path("data/cookies.json"))
    verify.add_argument("--raw-output", type=Path, default=Path("data/raw_order_responses.jsonl"))
    verify.add_argument("--log", type=Path, default=Path("data/status_verification.jsonl"))
    verify.add_argument("--interval", type=positive_seconds)
    return parser
```

Use `asyncio.run` for `verify`. Open one `JdOrderPage` context, then for each iteration call capture in `asyncio.to_thread`, flatten payloads, collect page statuses, compare, and print only summary counts. On page failure append a run-level `page_error` without raw order data. With no interval, break after one iteration; otherwise `await asyncio.sleep(interval)`. Let `KeyboardInterrupt` close the browser context and return success after printing a generic stop message.

README must document `.venv/bin/playwright install chromium`, visible-browser login expectations, both commands, local-only logs, and the meanings of every verification result.

- [ ] **Step 4: Run all automated tests and compile verification**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m compileall jd_monitor`

Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/__main__.py tests/test_cli.py README.md
git commit -m "feat: add continuous JD status verification"
```

## Final verification

- [ ] Run `.venv/bin/python -m pytest -q`.
- [ ] Run `.venv/bin/python -m compileall jd_monitor`.
- [ ] Install Chromium with `.venv/bin/playwright install chromium` if not already present.
- [ ] Run `.venv/bin/python -m jd_monitor verify` with the local ignored Cookie file.
- [ ] Confirm `data/status_verification.jsonl` contains no customer name, phone, address, remark, product, or Cookie fields.
- [ ] Confirm the five existing completed orders remain 5/5 `matched` in the first real run.
- [ ] Run `.venv/bin/python -m jd_monitor verify --interval 60` for at least two iterations and confirm records append without restarting Chromium.
