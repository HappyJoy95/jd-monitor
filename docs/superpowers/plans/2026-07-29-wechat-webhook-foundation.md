# Enterprise WeChat Webhook Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe local Enterprise WeChat robot test sender, an append-only processing audit log, and an empty post-order-pool processing hook without defining or creating a push pool.

**Architecture:** Keep four responsibilities separate: `processing_log.py` appends privacy-safe audit events, `wechat_webhook.py` loads and calls the robot URL, `message_processing.py` provides the deliberately empty processing boundary, and `__main__.py` wires them into explicit CLI flows. The capture path invokes the empty processor only after the order pool succeeds; the only network send in this phase is the explicit `wechat-test` command.

**Tech Stack:** Python 3.9+, standard library (`argparse`, `dataclasses`, `datetime`, `json`, `pathlib`, `urllib.parse`, `zoneinfo`), `requests`, `pytest`

---

## File Structure

- Create `jd_monitor/processing_log.py`: append privacy-safe JSONL audit events and normalize timestamps.
- Create `tests/test_processing_log.py`: verify append behavior, JSON shape, and safe failure handling.
- Create `jd_monitor/wechat_webhook.py`: read and validate the local Webhook URL and send a text message safely.
- Create `tests/test_wechat_webhook.py`: cover configuration, HTTP, JSON, business, network, and secret-redaction behavior.
- Create `jd_monitor/message_processing.py`: define the empty post-pool processor and its result/error types.
- Create `tests/test_message_processing.py`: verify empty output, audit events, and failure behavior.
- Modify `jd_monitor/__main__.py`: add `wechat-test` and call the empty processor after successful capture/pool refresh.
- Modify `tests/test_cli.py`: cover CLI parsing, test sends, hook ordering, skipped hooks, and safe errors.
- Modify `README.md`: document the private Webhook file, test command, processing log, and explicitly deferred push-pool behavior.

### Task 1: Privacy-Safe Append-Only Processing Log

**Files:**
- Create: `jd_monitor/processing_log.py`
- Create: `tests/test_processing_log.py`

- [ ] **Step 1: Write the failing processing-log tests**

Create `tests/test_processing_log.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jd_monitor.processing_log import ProcessingLogError, append_processing_event


def test_append_processing_event_creates_jsonl_and_preserves_existing_events(
    tmp_path: Path,
):
    log_path = tmp_path / "nested" / "push_processing.jsonl"
    first_time = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    second_time = datetime(2026, 7, 29, 12, 1, tzinfo=timezone.utc)

    append_processing_event(
        log_path,
        event="processor_started",
        status="started",
        now=first_time,
    )
    append_processing_event(
        log_path,
        event="processor_finished",
        status="no_messages",
        now=second_time,
    )

    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records == [
        {
            "occurred_at": "2026-07-29T20:00:00+08:00",
            "event": "processor_started",
            "status": "started",
        },
        {
            "occurred_at": "2026-07-29T20:01:00+08:00",
            "event": "processor_finished",
            "status": "no_messages",
        },
    ]


def test_append_processing_event_accepts_only_explicit_safe_error_code(
    tmp_path: Path,
):
    log_path = tmp_path / "push_processing.jsonl"

    append_processing_event(
        log_path,
        event="webhook_test_finished",
        status="failed",
        error_code="network_error",
    )

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["error_code"] == "network_error"
    assert set(record) == {"occurred_at", "event", "status", "error_code"}


def test_append_processing_event_wraps_file_errors(tmp_path: Path):
    log_path = tmp_path / "directory-instead-of-file"
    log_path.mkdir()

    with pytest.raises(ProcessingLogError, match="无法写入处理日志"):
        append_processing_event(
            log_path,
            event="processor_started",
            status="started",
        )
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run:

```bash
.venv/bin/python -m pytest tests/test_processing_log.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'jd_monitor.processing_log'`.

- [ ] **Step 3: Implement the processing log**

Create `jd_monitor/processing_log.py`:

```python
"""Append privacy-safe processing events to a local JSONL audit log."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


class ProcessingLogError(RuntimeError):
    """Raised when a processing audit event cannot be persisted."""


def _as_shanghai(now: datetime | None) -> datetime:
    value = now or datetime.now(SHANGHAI)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def append_processing_event(
    log_path: Path | str,
    *,
    event: str,
    status: str,
    error_code: str | None = None,
    now: datetime | None = None,
) -> None:
    """Append one event containing no order data or authentication values."""

    record = {
        "occurred_at": _as_shanghai(now).isoformat(),
        "event": event,
        "status": status,
    }
    if error_code is not None:
        record["error_code"] = error_code

    path = Path(log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            output.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        raise ProcessingLogError("无法写入处理日志") from exc
```

- [ ] **Step 4: Run the processing-log tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_processing_log.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the processing log**

```bash
git add jd_monitor/processing_log.py tests/test_processing_log.py
git commit -m "feat: add safe processing audit log"
```

### Task 2: Enterprise WeChat Webhook Configuration and Sender

**Files:**
- Create: `jd_monitor/wechat_webhook.py`
- Create: `tests/test_wechat_webhook.py`

- [ ] **Step 1: Write failing tests for local configuration**

Create `tests/test_wechat_webhook.py` with the configuration tests:

```python
from pathlib import Path

import pytest
import requests

from jd_monitor.wechat_webhook import (
    WechatWebhookClient,
    WechatWebhookError,
    load_webhook_url,
)


VALID_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    "?key=11111111-2222-3333-4444-555555555555"
)


def test_load_webhook_url_strips_whitespace(tmp_path: Path):
    path = tmp_path / "wechat_webhook.txt"
    path.write_text(f"\n {VALID_URL} \n", encoding="utf-8")

    assert load_webhook_url(path) == VALID_URL


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "   \n",
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
        "https://example.com/cgi-bin/webhook/send?key=secret",
        "https://qyapi.weixin.qq.com/not-webhook?key=secret",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
    ],
)
def test_load_webhook_url_rejects_empty_or_invalid_values(
    tmp_path: Path,
    contents: str,
):
    path = tmp_path / "wechat_webhook.txt"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(WechatWebhookError) as exc_info:
        load_webhook_url(path)

    assert VALID_URL not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_load_webhook_url_wraps_missing_file_without_leaking_path_secret(
    tmp_path: Path,
):
    path = tmp_path / "key=do-not-print.txt"

    with pytest.raises(WechatWebhookError, match="无法读取 Webhook 配置") as exc_info:
        load_webhook_url(path)

    assert "do-not-print" not in str(exc_info.value)
```

- [ ] **Step 2: Run the configuration tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_wechat_webhook.py -v
```

Expected: collection fails because `jd_monitor.wechat_webhook` does not exist.

- [ ] **Step 3: Implement configuration loading and validation**

Create the first part of `jd_monitor/wechat_webhook.py`:

```python
"""Send privacy-safe test messages to an Enterprise WeChat group robot."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


class WechatWebhookError(RuntimeError):
    """A safe error that never contains the Webhook URL."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def load_webhook_url(path: Path | str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WechatWebhookError(
            "无法读取 Webhook 配置",
            code="config_unreadable",
        ) from exc

    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    if (
        not value
        or parsed.scheme != "https"
        or parsed.hostname != "qyapi.weixin.qq.com"
        or parsed.path != "/cgi-bin/webhook/send"
        or not query.get("key")
        or not query["key"][0].strip()
    ):
        raise WechatWebhookError(
            "Webhook 地址格式不正确",
            code="config_invalid",
        )
    return value
```

- [ ] **Step 4: Run the configuration tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_wechat_webhook.py -v
```

Expected: the configuration tests pass.

- [ ] **Step 5: Add failing sender tests**

Append to `tests/test_wechat_webhook.py`:

```python
class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def test_send_text_posts_enterprise_wechat_text_payload():
    session = FakeSession(
        response=FakeResponse(payload={"errcode": 0, "errmsg": "ok"})
    )

    WechatWebhookClient(VALID_URL, session=session).send_text("连接测试")

    assert session.calls == [
        (
            VALID_URL,
            {"msgtype": "text", "text": {"content": "连接测试"}},
            15,
        )
    ]


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (FakeResponse(status_code=500), "http_error"),
        (
            FakeResponse(json_error=ValueError("invalid json")),
            "response_invalid",
        ),
        (
            FakeResponse(payload={"errcode": 93000, "errmsg": "denied"}),
            "business_error",
        ),
        (FakeResponse(payload=["not", "an", "object"]), "response_invalid"),
    ],
)
def test_send_text_converts_response_failures_to_safe_errors(
    response,
    expected_code,
):
    session = FakeSession(response=response)

    with pytest.raises(WechatWebhookError) as exc_info:
        WechatWebhookClient(VALID_URL, session=session).send_text("连接测试")

    assert exc_info.value.code == expected_code
    assert VALID_URL not in str(exc_info.value)
    assert "11111111" not in str(exc_info.value)


def test_send_text_converts_network_failure_without_leaking_request_url():
    session = FakeSession(
        error=requests.RequestException(f"failed request to {VALID_URL}")
    )

    with pytest.raises(WechatWebhookError) as exc_info:
        WechatWebhookClient(VALID_URL, session=session).send_text("连接测试")

    assert exc_info.value.code == "network_error"
    assert VALID_URL not in str(exc_info.value)
    assert "11111111" not in str(exc_info.value)
```

- [ ] **Step 6: Implement the Webhook sender**

Append to `jd_monitor/wechat_webhook.py`:

```python
class WechatWebhookClient:
    def __init__(
        self,
        webhook_url: str,
        *,
        session: requests.Session | None = None,
    ):
        self.webhook_url = webhook_url
        self.session = session or requests.Session()

    def send_text(self, content: str) -> None:
        try:
            response = self.session.post(
                self.webhook_url,
                json={"msgtype": "text", "text": {"content": content}},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise WechatWebhookError(
                "Webhook 网络请求失败",
                code="network_error",
            ) from exc

        if response.status_code != 200:
            raise WechatWebhookError(
                "Webhook 返回了非成功 HTTP 状态",
                code="http_error",
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise WechatWebhookError(
                "Webhook 响应格式无效",
                code="response_invalid",
            ) from exc
        if not isinstance(payload, dict) or "errcode" not in payload:
            raise WechatWebhookError(
                "Webhook 响应格式无效",
                code="response_invalid",
            )
        if payload["errcode"] != 0:
            raise WechatWebhookError(
                "企业微信机器人拒绝了消息",
                code="business_error",
            )
```

- [ ] **Step 7: Run all Webhook unit tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_wechat_webhook.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 8: Commit the Webhook module**

```bash
git add jd_monitor/wechat_webhook.py tests/test_wechat_webhook.py
git commit -m "feat: add enterprise wechat webhook client"
```

### Task 3: Empty Post-Pool Message Processor

**Files:**
- Create: `jd_monitor/message_processing.py`
- Create: `tests/test_message_processing.py`

- [ ] **Step 1: Write failing empty-processor tests**

Create `tests/test_message_processing.py`:

```python
import json
from pathlib import Path

import pytest

from jd_monitor.message_processing import (
    MessageProcessingError,
    process_order_pool,
)


def test_process_order_pool_returns_no_messages_and_writes_audit_events(
    tmp_path: Path,
):
    pool_path = tmp_path / "order_pool.json"
    log_path = tmp_path / "push_processing.jsonl"
    pool_path.write_text('{"1001":{"order":{"orderId":1001}}}\n', encoding="utf-8")

    result = process_order_pool(pool_path, log_path)

    assert result.messages == 0
    assert not (tmp_path / "push_pool.json").exists()
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [(record["event"], record["status"]) for record in records] == [
        ("processor_started", "started"),
        ("processor_finished", "no_messages"),
    ]
    serialized = json.dumps(records, ensure_ascii=False)
    assert "1001" not in serialized
    assert "orderId" not in serialized


def test_process_order_pool_rejects_missing_pool_and_logs_safe_failure(
    tmp_path: Path,
):
    log_path = tmp_path / "push_processing.jsonl"

    with pytest.raises(MessageProcessingError, match="订单池不可用"):
        process_order_pool(tmp_path / "missing.json", log_path)

    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["event"] == "processor_finished"
    assert records[-1]["status"] == "failed"
    assert records[-1]["error_code"] == "order_pool_unavailable"


def test_process_order_pool_wraps_log_failure(tmp_path: Path):
    pool_path = tmp_path / "order_pool.json"
    pool_path.write_text("{}\n", encoding="utf-8")
    log_path = tmp_path / "log-is-a-directory"
    log_path.mkdir()

    with pytest.raises(MessageProcessingError, match="消息处理日志写入失败"):
        process_order_pool(pool_path, log_path)
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run:

```bash
.venv/bin/python -m pytest tests/test_message_processing.py -v
```

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the empty processor**

Create `jd_monitor/message_processing.py`:

```python
"""Provide the deliberately empty post-order-pool processing boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .processing_log import ProcessingLogError, append_processing_event


class MessageProcessingError(RuntimeError):
    """Raised when post-pool processing cannot finish safely."""


@dataclass(frozen=True)
class MessageProcessingResult:
    messages: int


def process_order_pool(
    pool_path: Path | str,
    log_path: Path | str,
) -> MessageProcessingResult:
    """Record one empty processing pass without reading or exporting orders."""

    try:
        append_processing_event(
            log_path,
            event="processor_started",
            status="started",
        )
        if not Path(pool_path).is_file():
            append_processing_event(
                log_path,
                event="processor_finished",
                status="failed",
                error_code="order_pool_unavailable",
            )
            raise MessageProcessingError("订单池不可用")
        append_processing_event(
            log_path,
            event="processor_finished",
            status="no_messages",
        )
    except ProcessingLogError as exc:
        raise MessageProcessingError("消息处理日志写入失败") from exc
    return MessageProcessingResult(messages=0)
```

- [ ] **Step 4: Run the empty-processor tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_message_processing.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the processing boundary**

```bash
git add jd_monitor/message_processing.py tests/test_message_processing.py
git commit -m "feat: add empty order message processor"
```

### Task 4: Manual Webhook Test Command

**Files:**
- Modify: `jd_monitor/__main__.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing parser and successful-send CLI tests**

Update imports at the top of `tests/test_cli.py`:

```python
from jd_monitor.message_processing import MessageProcessingError
from jd_monitor.processing_log import ProcessingLogError
from jd_monitor.wechat_webhook import WechatWebhookError
```

Append:

```python
def test_wechat_test_parser_uses_private_local_defaults():
    args = cli.build_parser().parse_args(["wechat-test"])

    assert args.webhook == Path("data/wechat_webhook.txt")
    assert args.processing_log == Path("data/push_processing.jsonl")


def test_wechat_test_sends_fixed_message_and_logs_success(
    monkeypatch,
    capsys,
    tmp_path: Path,
):
    webhook_path = tmp_path / "wechat_webhook.txt"
    log_path = tmp_path / "processing.jsonl"
    calls = []

    class FakeClient:
        def __init__(self, url):
            calls.append(("client", url))

        def send_text(self, content):
            calls.append(("send", content))

    monkeypatch.setattr(cli, "load_webhook_url", lambda path: f"url-from:{path}")
    monkeypatch.setattr(cli, "WechatWebhookClient", FakeClient)
    monkeypatch.setattr(
        cli,
        "append_processing_event",
        lambda path, **event: calls.append(("log", path, event)),
    )

    assert cli.main([
        "wechat-test",
        "--webhook",
        str(webhook_path),
        "--processing-log",
        str(log_path),
    ]) == 0

    assert calls == [
        ("client", f"url-from:{webhook_path}"),
        ("send", "京东订单监控：企业微信机器人连接测试成功。"),
        (
            "log",
            log_path,
            {"event": "webhook_test_finished", "status": "succeeded"},
        ),
    ]
    captured = capsys.readouterr()
    assert captured.out == "企业微信机器人测试消息发送成功。\n"
    assert captured.err == ""
```

- [ ] **Step 2: Run the new CLI tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_cli.py::test_wechat_test_parser_uses_private_local_defaults \
  tests/test_cli.py::test_wechat_test_sends_fixed_message_and_logs_success -v
```

Expected: tests fail because the command and imported CLI symbols do not exist.

- [ ] **Step 3: Add the command parser and success path**

Add imports to `jd_monitor/__main__.py`:

```python
from .message_processing import MessageProcessingError, process_order_pool
from .processing_log import ProcessingLogError, append_processing_event
from .wechat_webhook import (
    WechatWebhookClient,
    WechatWebhookError,
    load_webhook_url,
)
```

Add to `build_parser()` after the `pool` arguments:

```python
    wechat_test = commands.add_parser(
        "wechat-test",
        help="发送企业微信机器人测试消息",
    )
    wechat_test.add_argument(
        "--webhook",
        type=Path,
        default=Path("data/wechat_webhook.txt"),
    )
    wechat_test.add_argument(
        "--processing-log",
        type=Path,
        default=Path("data/push_processing.jsonl"),
    )
```

Add above `main()`:

```python
WECHAT_TEST_MESSAGE = "京东订单监控：企业微信机器人连接测试成功。"


def _run_wechat_test(args: argparse.Namespace) -> int:
    try:
        webhook_url = load_webhook_url(args.webhook)
        WechatWebhookClient(webhook_url).send_text(WECHAT_TEST_MESSAGE)
        append_processing_event(
            args.processing_log,
            event="webhook_test_finished",
            status="succeeded",
        )
    except (WechatWebhookError, ProcessingLogError):
        print(
            "企业微信机器人测试失败：请检查本机 Webhook 配置、网络和处理日志路径。",
            file=sys.stderr,
        )
        return 1

    print("企业微信机器人测试消息发送成功。")
    return 0
```

Add inside `main()` before the final `return 2`:

```python
    if args.command == "wechat-test":
        return _run_wechat_test(args)
```

- [ ] **Step 4: Run the successful-send CLI tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_cli.py::test_wechat_test_parser_uses_private_local_defaults \
  tests/test_cli.py::test_wechat_test_sends_fixed_message_and_logs_success -v
```

Expected: `2 passed`.

- [ ] **Step 5: Add failing tests for Webhook failure and log failure**

Append to `tests/test_cli.py`:

```python
def test_wechat_test_logs_safe_webhook_failure(
    monkeypatch,
    capsys,
    tmp_path: Path,
):
    secret_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET"
    log_path = tmp_path / "processing.jsonl"
    calls = []

    class FailingClient:
        def __init__(self, _url):
            pass

        def send_text(self, _content):
            raise WechatWebhookError("safe failure", code="network_error")

    monkeypatch.setattr(cli, "load_webhook_url", lambda _path: secret_url)
    monkeypatch.setattr(cli, "WechatWebhookClient", FailingClient)
    monkeypatch.setattr(
        cli,
        "append_processing_event",
        lambda path, **event: calls.append((path, event)),
    )

    assert cli.main([
        "wechat-test",
        "--processing-log",
        str(log_path),
    ]) == 1

    assert calls == [
        (
            log_path,
            {
                "event": "webhook_test_finished",
                "status": "failed",
                "error_code": "network_error",
            },
        )
    ]
    captured = capsys.readouterr()
    assert "SECRET" not in captured.err
    assert "safe failure" not in captured.err


def test_wechat_test_reports_log_failure_without_leaking_webhook(
    monkeypatch,
    capsys,
):
    secret_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET"

    class FakeClient:
        def __init__(self, _url):
            pass

        def send_text(self, _content):
            pass

    monkeypatch.setattr(cli, "load_webhook_url", lambda _path: secret_url)
    monkeypatch.setattr(cli, "WechatWebhookClient", FakeClient)
    monkeypatch.setattr(
        cli,
        "append_processing_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProcessingLogError("SECRET")
        ),
    )

    assert cli.main(["wechat-test"]) == 1
    captured = capsys.readouterr()
    assert "SECRET" not in captured.err
    assert secret_url not in captured.err
```

- [ ] **Step 6: Log safe Webhook failures**

Replace `_run_wechat_test()` with:

```python
def _run_wechat_test(args: argparse.Namespace) -> int:
    try:
        webhook_url = load_webhook_url(args.webhook)
        WechatWebhookClient(webhook_url).send_text(WECHAT_TEST_MESSAGE)
    except WechatWebhookError as exc:
        try:
            append_processing_event(
                args.processing_log,
                event="webhook_test_finished",
                status="failed",
                error_code=exc.code,
            )
        except ProcessingLogError:
            pass
        print(
            "企业微信机器人测试失败：请检查本机 Webhook 配置、网络和处理日志路径。",
            file=sys.stderr,
        )
        return 1

    try:
        append_processing_event(
            args.processing_log,
            event="webhook_test_finished",
            status="succeeded",
        )
    except ProcessingLogError:
        print(
            "测试消息已发送，但处理日志写入失败：请检查日志路径。",
            file=sys.stderr,
        )
        return 1

    print("企业微信机器人测试消息发送成功。")
    return 0
```

- [ ] **Step 7: Run all CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 8: Commit the manual test command**

```bash
git add jd_monitor/__main__.py tests/test_cli.py
git commit -m "feat: add wechat webhook test command"
```

### Task 5: Invoke the Empty Processor After Successful Capture

**Files:**
- Modify: `jd_monitor/__main__.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Extend the capture parser test and ordering test**

In `test_capture_parser_preserves_default_paths()`, add:

```python
    assert args.processing_log == Path("data/push_processing.jsonl")
```

In `test_capture_refreshes_explicit_pool_after_capture()`, add this monkeypatch:

```python
    monkeypatch.setattr(
        cli,
        "process_order_pool",
        lambda pool, log: calls.append(("process", pool, log)),
    )
```

Change the CLI invocation to include:

```python
        "--processing-log",
        str(tmp_path / "processing.jsonl"),
```

Change the expected calls to:

```python
    assert calls == [
        ("capture", raw_path),
        ("pool", raw_path, pool_path),
        ("process", pool_path, tmp_path / "processing.jsonl"),
    ]
```

In `test_capture_defaults_pool_to_raw_file_directory()`, add this monkeypatch:

```python
    monkeypatch.setattr(
        cli,
        "process_order_pool",
        lambda pool, log: calls.append(("process", pool, log)),
    )
```

Change its expected calls to:

```python
    assert calls == [
        (raw_path, raw_path.with_name("order_pool.json")),
        (
            "process",
            raw_path.with_name("order_pool.json"),
            Path("data/push_processing.jsonl"),
        ),
    ]
```

The first call retains the existing two-element pool-builder tuple; the second
call proves that the default processing log is passed to the new hook.

- [ ] **Step 2: Run the ordering tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_cli.py::test_capture_parser_preserves_default_paths \
  tests/test_cli.py::test_capture_refreshes_explicit_pool_after_capture -v
```

Expected: failures show that `capture` lacks `processing_log` and does not call the processor.

- [ ] **Step 3: Wire the processor into successful capture**

Add this argument to the `capture` parser in `build_parser()`:

```python
    capture.add_argument(
        "--processing-log",
        type=Path,
        default=Path("data/push_processing.jsonl"),
    )
```

In `_run_capture()`, after `build_order_pool()` succeeds and before the success `print()`, add:

```python
    try:
        process_order_pool(pool_result.output_path, args.processing_log)
    except MessageProcessingError:
        print(
            "采集和订单池已完成，但后续消息处理失败：请检查处理日志路径。",
            file=sys.stderr,
        )
        return 1
```

- [ ] **Step 4: Run the ordering tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_cli.py::test_capture_parser_preserves_default_paths \
  tests/test_cli.py::test_capture_refreshes_explicit_pool_after_capture -v
```

Expected: `2 passed`.

- [ ] **Step 5: Add tests proving failed upstream stages skip processing**

In `test_capture_pool_error_preserves_raw_log_and_hides_details()`, add:

```python
    processor_called = False

    def processor_should_not_run(_pool_path, _log_path):
        nonlocal processor_called
        processor_called = True

    monkeypatch.setattr(cli, "process_order_pool", processor_should_not_run)
```

Add after the existing assertions:

```python
    assert processor_called is False
```

In `test_capture_error_does_not_refresh_pool()`, add:

```python
    processor_called = False

    def processor_should_not_run(_pool_path, _log_path):
        nonlocal processor_called
        processor_called = True

    monkeypatch.setattr(cli, "process_order_pool", processor_should_not_run)
```

Add after the existing assertions:

```python
    assert processor_called is False
```

- [ ] **Step 6: Add a failing safe processor-error test**

Append to `tests/test_cli.py`:

```python
def test_capture_reports_processing_failure_after_preserving_pool(
    monkeypatch,
    capsys,
    tmp_path: Path,
):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "order_pool.json"

    class FakeCapture:
        def __init__(self, _session, _output_path):
            pass

        def capture_once(self):
            return SimpleNamespace(pages=1, responses=1)

    def fake_build_order_pool(_input, output):
        output.write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(unique_orders=0, output_path=output)

    def fail_processing(_pool, _log):
        raise MessageProcessingError("SECRET")

    monkeypatch.setattr(cli, "session_from_cookie_file", lambda _: object())
    monkeypatch.setattr(cli, "OrderCapture", FakeCapture)
    monkeypatch.setattr(cli, "build_order_pool", fake_build_order_pool)
    monkeypatch.setattr(cli, "process_order_pool", fail_processing)

    assert cli.main([
        "capture",
        "--output",
        str(raw_path),
        "--pool",
        str(pool_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "采集和订单池已完成，但后续消息处理失败：请检查处理日志路径。\n"
    )
    assert "SECRET" not in captured.err
    assert pool_path.read_text(encoding="utf-8") == "{}\n"
```

- [ ] **Step 7: Run all CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: all CLI tests pass, including the upstream-skip and safe downstream-failure cases.

- [ ] **Step 8: Commit capture integration**

```bash
git add jd_monitor/__main__.py tests/test_cli.py
git commit -m "feat: run empty processor after capture"
```

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Verify: `jd_monitor/*.py`
- Verify: `tests/*.py`

- [ ] **Step 1: Add Webhook setup and test instructions to README**

Append this section to `README.md`:

```markdown
## 企业微信群机器人连接测试

将企业微信群机器人的完整 Webhook 地址保存为本机文件：

`data/wechat_webhook.txt`

文件只放一行完整地址。Webhook 地址相当于密钥；不要提交到 Git、不要发送到聊天中，也不要复制到日志。

发送一条不包含订单信息的固定测试消息：

```bash
.venv/bin/python -m jd_monitor wechat-test
```

可以显式指定私有配置文件和处理日志：

```bash
.venv/bin/python -m jd_monitor wechat-test \
  --webhook data/wechat_webhook.txt \
  --processing-log data/push_processing.jsonl
```

测试结果与订单池后的空处理步骤会追加记录到
`data/push_processing.jsonl`。日志不包含 Cookie、Webhook 地址或完整订单内容。

当前版本在订单池更新成功后只运行一个空处理器，不生成推送池，也不会自动发送订单信息。订单筛选、消息内容计算、推送池结构和订单消息自动发送将在这些规则确定后另行实现。
```

- [ ] **Step 2: Confirm ignored private files**

Run:

```bash
git check-ignore data/wechat_webhook.txt data/push_processing.jsonl
```

Expected:

```text
data/wechat_webhook.txt
data/push_processing.jsonl
```

- [ ] **Step 3: Run the full automated test suite**

Run:

```bash
.venv/bin/python -m pytest -v
```

Expected: all existing and new tests pass.

- [ ] **Step 4: Check formatting errors and repository scope**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` lists only the intended Python, test, and README changes for this task.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain wechat webhook foundation"
```

- [ ] **Step 6: Perform a safe local CLI smoke test without a real Webhook**

Run:

```bash
.venv/bin/python -m jd_monitor wechat-test \
  --webhook data/nonexistent-wechat-webhook.txt \
  --processing-log data/push_processing.jsonl
```

Expected: exit code `1`; terminal output gives the safe configuration/network/log guidance and does not print the supplied path as a URL or any secret value. `data/push_processing.jsonl` receives a failure event with `error_code` equal to `config_unreadable`.

Do not send a real test message during automated implementation. A real Webhook test is an explicit user-operated verification after they populate the private file.
