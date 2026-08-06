# 京东到家订单原始采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local command that reads a private browser-cookie file, captures every page of the web order-list API, and appends the unmodified JSON responses to a JSONL file.

**Architecture:** A focused capture module owns query-window construction, cookie-session creation, HTTP pagination, and append-only persistence. A small CLI calls it once and prints only non-sensitive run counts; it never interprets the content of any order response.

**Tech Stack:** Python 3.11+, requests, pytest, standard-library JSON and datetime modules.

---

## File structure

- `pyproject.toml`: package metadata, runtime dependency and pytest configuration.
- `.gitignore`: excludes private cookies and local captured data.
- `jd_monitor/capture.py`: public capture API, cookie loading, query generation, pagination and JSONL persistence.
- `jd_monitor/__main__.py`: `python -m jd_monitor capture` command.
- `tests/test_capture.py`: request, pagination, persistence and failure behavior tests.
- `README.md`: setup, private cookie-file format and one-shot capture command.

### Task 1: Create the testable capture module

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `jd_monitor/__init__.py`
- Create: `jd_monitor/capture.py`
- Create: `tests/test_capture.py`

- [ ] **Step 1: Write the failing single-page capture test**

```python
from datetime import datetime
from pathlib import Path

from jd_monitor.capture import OrderCapture


def test_capture_appends_unmodified_response_with_request_metadata(tmp_path: Path):
    captured: list[dict] = []

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"code": "0", "result": {"orders": ["unchanged"]}}

    class Session:
        def get(self, url, *, params, timeout):
            captured.append({"url": url, "params": params, "timeout": timeout})
            return Response()

    output = tmp_path / "raw_order_responses.jsonl"
    result = OrderCapture(Session(), output).capture_once(
        now=datetime(2026, 7, 29, 13, 44, 53)
    )

    assert result.pages == 1
    assert captured[0]["params"]["endTimeQuery"] == "2026-07-29 13:44:53"
    assert output.read_text(encoding="utf-8").splitlines() == [
        '{"captured_at":"2026-07-29T13:44:53+08:00","request":{"page_no":1,"page_size":50,"start_time_query":"2026-07-29 00:00:00","end_time_query":"2026-07-29 13:44:53","pre_start_delivery_time":"2026-07-29 00:00:00","pre_end_delivery_time":"2026-07-29 23:59:59","station_no":""},"response":{"code":"0","result":{"orders":["unchanged"]}}}'
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_capture.py::test_capture_appends_unmodified_response_with_request_metadata -q`

Expected: FAIL because `jd_monitor.capture` does not exist.

- [ ] **Step 3: Implement the smallest capture API**

```python
ORDER_LIST_URL = "https://order.jddj.com/order/newManager/tabQuery/all"

class OrderCapture:
    def __init__(self, session, output_path):
        self.session = session
        self.output_path = Path(output_path)

    def capture_once(self, now=None):
        ...  # request page 1 with dynamic Asia/Shanghai time parameters
        ...  # validate JSON, append one compact JSON object, return CaptureResult
```

`capture_once` must write UTF-8 JSONL, create its parent directory, preserve the decoded response object under `response` without selecting or transforming its fields, and raise `CaptureError` for any non-200 response or invalid JSON.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m pytest tests/test_capture.py::test_capture_appends_unmodified_response_with_request_metadata -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore jd_monitor tests/test_capture.py
git commit -m "feat: add raw order capture"
```

### Task 2: Add safe cookie loading and complete pagination

**Files:**
- Modify: `jd_monitor/capture.py`
- Modify: `tests/test_capture.py`

- [ ] **Step 1: Write the failing cookie and two-page capture tests**

```python
def test_session_from_cookie_file_loads_playwright_cookies_without_logging_them(tmp_path):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text('[{"name":"thor","value":"secret","domain":"order.jddj.com","path":"/"}]')

    session = session_from_cookie_file(cookie_path)

    assert session.cookies.get("thor", domain="order.jddj.com", path="/") == "secret"


def test_capture_writes_each_page_when_total_count_requires_pagination(tmp_path):
    responses = [
        {"code": "0", "result": {"newOrderinfoMains": {"totalCount": 51}}},
        {"code": "0", "result": {"newOrderinfoMains": {"totalCount": 51}}},
    ]
    session = FakeSession(responses)

    result = OrderCapture(session, tmp_path / "raw.jsonl").capture_once(
        now=datetime(2026, 7, 29, 13, 44, 53)
    )

    assert result.pages == 2
    assert [call["params"]["pageNo"] for call in session.calls] == [1, 2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_capture.py -q`

Expected: FAIL because `session_from_cookie_file` and pagination do not exist.

- [ ] **Step 3: Implement private-cookie loading and pagination**

```python
def session_from_cookie_file(cookie_path):
    cookies = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    for cookie in cookies:
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie.get("path", "/"))
    return session
```

Read `result.newOrderinfoMains.totalCount` only to decide the page count; retain every whole response as raw data. A malformed total count stops after the first page. No exception text may include a Cookie value.

- [ ] **Step 4: Run the test suite to verify it passes**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/capture.py tests/test_capture.py
git commit -m "feat: load cookies and paginate order capture"
```

### Task 3: Add a one-shot CLI and operating instructions

**Files:**
- Create: `jd_monitor/__main__.py`
- Create: `README.md`
- Modify: `tests/test_capture.py`

- [ ] **Step 1: Write the failing CLI success test**

```python
def test_main_capture_reports_counts_without_response_or_cookie_content(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("jd_monitor.__main__.session_from_cookie_file", lambda _: object())
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)

    exit_code = main(["capture", "--cookies", str(tmp_path / "cookies.json"), "--output", str(tmp_path / "raw.jsonl")])

    assert exit_code == 0
    assert capsys.readouterr().out == "采集完成：2 页，2 个响应。\\n"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_capture.py::test_main_capture_reports_counts_without_response_or_cookie_content -q`

Expected: FAIL because `jd_monitor.__main__` does not exist.

- [ ] **Step 3: Implement the CLI and README**

```python
def main(argv=None):
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--cookies", type=Path, default=Path("data/cookies.json"))
    capture.add_argument("--output", type=Path, default=Path("data/raw_order_responses.jsonl"))
    ...
```

The command must print only page and response counts on success, print a generic failure message to stderr on `CaptureError`, and return a nonzero exit code. README must document that the cookie file is local-only, is never to be pasted into chat, and that `python -m jd_monitor capture` performs one collection.

- [ ] **Step 4: Run all tests and syntax verification**

Run: `python -m pytest -q && python -m compileall jd_monitor`

Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/__main__.py README.md tests/test_capture.py
git commit -m "feat: add order capture command"
```

## Final verification

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall jd_monitor`.
- [ ] With a newly created local `data/cookies.json`, run `python -m jd_monitor capture` once.
- [ ] Confirm the output command prints counts only and that `data/raw_order_responses.jsonl` contains an unmodified `response` object.
