# 京东到家订单监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent local web application that monitors Jingdong Daojia orders, supports interactive Cookie refresh, and sends configurable notifications.

**Architecture:** A FastAPI process serves a static single-page management UI and JSON API. Focused services handle persistent settings, the Jingdong API/browser clients, polling orchestration, and notification delivery; APScheduler invokes the orchestrator on the configured interval.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, APScheduler, requests, Playwright, PyYAML, pytest, HTML/CSS/vanilla JavaScript.

---

## File structure

- `pyproject.toml`: runtime and test dependencies plus pytest configuration.
- `jd_monitor/config.py`: typed settings defaults, validation, YAML persistence and runtime paths.
- `jd_monitor/models.py`: dataclasses shared between the order client, run service and API.
- `jd_monitor/storage.py`: atomic JSON read/write for cookies, latest result, history and run log.
- `jd_monitor/jddj.py`: API client and status mapping/target-order helpers.
- `jd_monitor/notifications.py`: notification message formatter and channel implementations.
- `jd_monitor/login.py`: exclusive headed Playwright Cookie refresh session.
- `jd_monitor/service.py`: API-first query, browser fallback, persistence and notifications.
- `jd_monitor/app.py`: FastAPI application, scheduler lifecycle and HTTP endpoints.
- `web/index.html`, `web/app.js`, `web/styles.css`: local browser management page.
- `tests/`: isolated behavior and API tests.
- `config/settings.example.yaml`, `.gitignore`, `README.md`: first-run configuration and operational documentation.

### Task 1: Create the independent project shell and configuration contract

**Files:**
- Create: `pyproject.toml`
- Create: `jd_monitor/__init__.py`
- Create: `jd_monitor/models.py`
- Create: `jd_monitor/config.py`
- Create: `config/settings.example.yaml`
- Create: `.gitignore`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing settings validation test**

```python
from pathlib import Path

import pytest

from jd_monitor.config import SettingsStore


def test_save_rejects_non_positive_poll_interval(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.yaml")

    with pytest.raises(ValueError, match="poll_interval_minutes"):
        store.save({"monitor": {"poll_interval_minutes": 0}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_save_rejects_non_positive_poll_interval -q`

Expected: FAIL because `jd_monitor.config` does not exist.

- [ ] **Step 3: Add the smallest package, data model and settings implementation**

```python
# jd_monitor/config.py
DEFAULT_SETTINGS = {
    "monitor": {"poll_interval_minutes": 5, "status_mapping": []},
    "notifications": {"enabled": False, "types": []},
}

class SettingsStore:
    def __init__(self, path): self.path = Path(path)
    def load(self): ...  # merge YAML data into a deep copy of DEFAULT_SETTINGS
    def save(self, data):
        minutes = data["monitor"]["poll_interval_minutes"]
        if not isinstance(minutes, int) or minutes < 1:
            raise ValueError("monitor.poll_interval_minutes must be a positive integer")
        ...  # create parent and yaml.safe_dump(..., allow_unicode=True, sort_keys=False)
```

Add `Order` and `RunResult` dataclasses in `models.py`, include runtime packages in `pyproject.toml`, and add `.gitignore` entries for `.venv/`, `__pycache__/`, `.pytest_cache/`, `data/`, and `config/settings.yaml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py::test_save_rejects_non_positive_poll_interval -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml jd_monitor tests/test_config.py config/settings.example.yaml .gitignore
git commit -m "feat: add JD monitor configuration"
```

### Task 2: Implement local result persistence and order classification

**Files:**
- Create: `jd_monitor/storage.py`
- Create: `jd_monitor/jddj.py`
- Test: `tests/test_jddj.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing target-order test**

```python
from jd_monitor.jddj import select_target_orders
from jd_monitor.models import Order


def test_select_target_orders_uses_only_enabled_status_names():
    orders = [Order(order_id="1", status="待接单"), Order(order_id="2", status="配送中")]
    mappings = [{"code": "0", "name": "待接单", "enabled": True}]

    assert [order.order_id for order in select_target_orders(orders, mappings)] == ["1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jddj.py::test_select_target_orders_uses_only_enabled_status_names -q`

Expected: FAIL because `select_target_orders` does not exist.

- [ ] **Step 3: Implement standard order mapping, selection and JSON storage**

```python
def select_target_orders(orders, mappings):
    enabled_names = {item["name"] for item in mappings if item.get("enabled")}
    return [order for order in orders if order.status in enabled_names]

def map_order(raw, status_mapping):
    return Order(
        order_id=str(raw.get("orderId", "")),
        status=status_mapping.get(str(raw.get("stationOrderStatus")), f"未知({raw.get('stationOrderStatus')})"),
        store_name=raw.get("stationName", ""),
        amount=raw.get("orderTotalPrice", 0),
    )
```

Implement `JsonStorage.write_latest`, `append_run`, and `append_history`. Use a temporary sibling file and `Path.replace()` for writes. De-duplicate history by `(order_id, status, date)` and retain the latest 500 run records.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m pytest tests/test_jddj.py tests/test_storage.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/storage.py jd_monitor/jddj.py tests/test_jddj.py tests/test_storage.py
git commit -m "feat: add order persistence and filtering"
```

### Task 3: Add API-first Jingdong client and headed Cookie login

**Files:**
- Create: `jd_monitor/login.py`
- Modify: `jd_monitor/jddj.py`
- Test: `tests/test_jddj_client.py`
- Test: `tests/test_login.py`

- [ ] **Step 1: Write the failing API response conversion test**

```python
from jd_monitor.jddj import JddjApiClient


def test_get_orders_returns_mapped_orders_from_success_response():
    client = JddjApiClient("cookies.json", {"0": "待接单"})
    client.session.get = lambda *args, **kwargs: FakeResponse({
        "code": "0",
        "result": {"newOrderinfoMains": {"totalCount": 1, "resultList": [
            {"orderId": 123, "stationOrderStatus": 0, "stationName": "朝阳店"}
        ]}},
    })

    result = client.get_orders("2026-07-29 00:00:00", "2026-07-29 23:59:59")

    assert result.orders[0].order_id == "123"
    assert result.orders[0].status == "待接单"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jddj_client.py::test_get_orders_returns_mapped_orders_from_success_response -q`

Expected: FAIL because `JddjApiClient` does not exist.

- [ ] **Step 3: Implement the API client and exclusive login service**

```python
class CookieLoginService:
    def __init__(self, cookies_path):
        self.cookies_path = Path(cookies_path)
        self._active = False

    async def refresh(self):
        if self._active:
            raise RuntimeError("登录流程正在进行")
        self._active = True
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto("https://store.jddj.com/", wait_until="domcontentloaded")
                await page.wait_for_url(lambda url: "login" not in url, timeout=300_000)
                write_json(self.cookies_path, await context.cookies())
                await browser.close()
        finally:
            self._active = False
```

`JddjApiClient` loads Playwright cookie JSON into a `requests.Session`, considers only response code `"0"` valid, paginates in pages of 50, and raises a named `JddjClientError` for invalid API data or request errors. Implement `browser_fetch_orders` as a separate Playwright function used only by the service fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_jddj_client.py tests/test_login.py -q`

Expected: PASS without launching a real browser.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/jddj.py jd_monitor/login.py tests/test_jddj_client.py tests/test_login.py
git commit -m "feat: add Jingdong client and cookie login"
```

### Task 4: Implement notification formatting and independent channels

**Files:**
- Create: `jd_monitor/notifications.py`
- Test: `tests/test_notifications.py`

- [ ] **Step 1: Write the failing message formatting test**

```python
from jd_monitor.models import Order
from jd_monitor.notifications import build_order_notification


def test_notification_lists_at_most_five_orders():
    orders = [Order(order_id=str(index), status="待接单", store_name="门店") for index in range(6)]

    title, content = build_order_notification(orders, "2026-07-29")

    assert title == "京东到家订单通知"
    assert "订单号：`0`" in content
    assert "订单号：`5`" not in content
    assert "还有 1 条订单" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notifications.py::test_notification_lists_at_most_five_orders -q`

Expected: FAIL because `build_order_notification` does not exist.

- [ ] **Step 3: Implement channel isolation and send result collection**

```python
def build_order_notification(orders, date):
    lines = [f"**日期：** {date}", f"**目标订单：{len(orders)} 条**", ""]
    for index, order in enumerate(orders[:5], 1):
        lines.extend([f"**{index}. {order.status}**", f"> 订单号：`{order.order_id}`", f"> 门店：{order.store_name}"])
    if len(orders) > 5:
        lines.append(f"\n_... 还有 {len(orders) - 5} 条订单_")
    return "京东到家订单通知", "\n".join(lines)
```

Create `WechatWebhookChannel`, `WechatAppRelayChannel`, and `SmtpEmailChannel`, each implementing `send(target, title, content) -> ChannelResult`. `NotificationService.send_configured` must attempt each selected valid channel and return all outcomes rather than stopping at the first failure. Credentials come from explicitly named environment variables when present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifications.py -q`

Expected: PASS with mocked HTTP and SMTP transports.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/notifications.py tests/test_notifications.py
git commit -m "feat: add notification channels"
```

### Task 5: Orchestrate a run and expose the FastAPI management API

**Files:**
- Create: `jd_monitor/service.py`
- Create: `jd_monitor/app.py`
- Test: `tests/test_service.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing API settings update test**

```python
from fastapi.testclient import TestClient
from jd_monitor.app import create_app


def test_put_settings_reschedules_monitor(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)

    response = client.put("/api/settings", json={
        "monitor": {"poll_interval_minutes": 10, "status_mapping": []},
        "notifications": {"enabled": False, "types": []},
    })

    assert response.status_code == 200
    assert app.state.scheduler.get_job("monitor").trigger.interval.total_seconds() == 600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app.py::test_put_settings_reschedules_monitor -q`

Expected: FAIL because `create_app` does not exist.

- [ ] **Step 3: Add the run service, endpoints and scheduler lifecycle**

```python
app = FastAPI()
app.get("/api/dashboard")(dashboard)
app.get("/api/settings")(get_settings)
app.put("/api/settings")(put_settings)
app.post("/api/run")(run_now)
app.post("/api/login/refresh")(refresh_cookie)
app.get("/api/login/status")(login_status)
app.post("/api/notifications/test")(test_notification)
app.get("/api/runs")(list_runs)
app.get("/api/history")(list_history)
```

`MonitorService.run_once` must: obtain API orders, fall back to browser only on `JddjClientError`, filter target statuses, persist latest/history/run information, notify only when target orders exist, and record a failed run on any unrecoverable error. `PUT /api/settings` validates before saving and calls `replace_existing=True` when rescheduling the APScheduler interval job. Serve `web/` at `/` with `StaticFiles`.

- [ ] **Step 4: Run service and HTTP tests**

Run: `python -m pytest tests/test_service.py tests/test_app.py -q`

Expected: PASS; tests use fake clients and do not access Jingdong or send notifications.

- [ ] **Step 5: Commit**

```bash
git add jd_monitor/service.py jd_monitor/app.py tests/test_service.py tests/test_app.py
git commit -m "feat: add monitor API and scheduler"
```

### Task 6: Build the local management page and ship operational guidance

**Files:**
- Create: `web/index.html`
- Create: `web/app.js`
- Create: `web/styles.css`
- Create: `README.md`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing static-page availability test**

```python
from fastapi.testclient import TestClient
from jd_monitor.app import create_app


def test_management_page_is_served(tmp_path):
    response = TestClient(create_app(tmp_path)).get("/")

    assert response.status_code == 200
    assert "京东到家订单监控" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::test_management_page_is_served -q`

Expected: FAIL because no static management page exists.

- [ ] **Step 3: Implement the single-page controls**

```html
<main>
  <h1>京东到家订单监控</h1>
  <section id="dashboard"></section>
  <button id="run-now">立即执行</button>
  <button id="refresh-cookie">登录/刷新 Cookie</button>
  <form id="monitor-settings"></form>
  <form id="notification-settings"></form>
</main>
```

`web/app.js` loads the dashboard/settings on page load, renders status mappings as editable rows, serializes settings forms to `PUT /api/settings`, polls login status while a login session is active, and surfaces server validation errors in an `aria-live` status element. `README.md` documents virtual-environment install, `playwright install chromium`, first start, Cookie refresh on a local GUI machine, environment variables, and the command `uvicorn jd_monitor.app:create_app --factory --host 127.0.0.1 --port 8765`.

- [ ] **Step 4: Run the entire test suite and manual smoke check**

Run: `python -m pytest -q`

Expected: PASS.

Run: `python -m uvicorn jd_monitor.app:create_app --factory --host 127.0.0.1 --port 8765`

Expected: The browser can open `http://127.0.0.1:8765`, show the dashboard, and return JSON from `/api/dashboard`.

- [ ] **Step 5: Commit**

```bash
git add web README.md tests/test_web.py
git commit -m "feat: add JD monitor web interface"
```

## Final verification

- [ ] Run `python -m pytest -q` and confirm all tests pass.
- [ ] Run `python -m compileall jd_monitor` and confirm no syntax errors.
- [ ] Start Uvicorn locally, open the management page, save an interval change, and verify the scheduler reflects it.
- [ ] On a GUI-capable machine, complete a headed Cookie refresh and verify `data/cookies.json` is created but ignored by Git.
- [ ] Use test notification endpoints with non-production targets before enabling real recipient addresses.
