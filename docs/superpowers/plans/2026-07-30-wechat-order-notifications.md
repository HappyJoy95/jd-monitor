# Enterprise WeChat Order Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send each active order to an Enterprise WeChat robot once after it has waited more than eight minutes.

**Architecture:** The capture command refreshes the local order pool, then a notification service selects eligible orders and consults a local sent-order ledger. The webhook client owns configuration validation and HTTP delivery; only a confirmed successful delivery records the order ID, making later minute-by-minute runs safe retries.

**Tech Stack:** Python 3.9+, `requests`, `pytest`, JSON files.

---

### Task 1: Safe Enterprise WeChat Webhook Client

**Files:**
- Create: `jd_monitor/wechat_webhook.py`
- Create: `tests/test_wechat_webhook.py`

- [ ] **Step 1: Write failing tests** for a URL read from `data/wechat_webhook.txt`, rejecting missing, empty, non-HTTPS, wrong-host, wrong-path, or missing-key values without exposing the URL; test `send_text` posts `{"msgtype":"text","text":{"content":...}}`, accepts HTTP 200 plus `errcode == 0`, and safely rejects network, HTTP, JSON, and business errors.
- [ ] **Step 2: Run** `python -m pytest tests/test_wechat_webhook.py -q`; expect collection failure because the module does not exist.
- [ ] **Step 3: Implement** `load_webhook_url(path)` with `urllib.parse` validation for `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...`, and `WechatWebhookClient.send_text(content)` with a 15-second timeout and redacted `WechatWebhookError(code=...)` errors.
- [ ] **Step 4: Run** `python -m pytest tests/test_wechat_webhook.py -q`; expect pass.

### Task 2: Durable Sent-Order Ledger

**Files:**
- Create: `jd_monitor/sent_orders.py`
- Create: `tests/test_sent_orders.py`

- [ ] **Step 1: Write failing tests** that an absent ledger returns an empty set, a valid JSON object stores and reloads sent order IDs, and malformed records or write errors raise safe errors.
- [ ] **Step 2: Run** `python -m pytest tests/test_sent_orders.py -q`; expect collection failure.
- [ ] **Step 3: Implement** atomic JSON persistence at `data/sent_orders.json`, storing `{order_id: {"sent_at": ISO-8601 timestamp}}`; write only after a confirmed webhook success.
- [ ] **Step 4: Run** `python -m pytest tests/test_sent_orders.py -q`; expect pass.

### Task 3: Eligibility and Message Construction

**Files:**
- Create: `jd_monitor/notifications.py`
- Create: `tests/test_notifications.py`

- [ ] **Step 1: Write failing tests** for orders with a valid `orderStartTime`: select only unsent orders older than eight minutes; reject missing or invalid time without sending; format a message with order number, store, status, order time, wait minutes, and product summary; never include `mobile`, `telephone`, or `fullAddress`.
- [ ] **Step 2: Run** `python -m pytest tests/test_notifications.py -q`; expect collection failure.
- [ ] **Step 3: Implement** `process_notifications(pool_path, webhook_url_path, ledger_path, now)` to read the existing pool, calculate Asia/Shanghai age from `orderStartTime`, call the Webhook client per eligible order, and add only successful sends to the ledger. Return attempted/sent/skipped counts; propagate safe failure on an unconfirmed send so it retries next minute.
- [ ] **Step 4: Run** `python -m pytest tests/test_notifications.py -q`; expect pass.

### Task 4: Command Integration and Scheduling Contract

**Files:**
- Modify: `jd_monitor/__main__.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests** that `capture` calls notification processing only after capture and pool refresh succeed, passes default paths next to the pool, reports safe counts, and does not process after capture or pool failure; add `wechat-test` to validate the robot without order data.
- [ ] **Step 2: Run** `python -m pytest tests/test_cli.py -q`; expect failures for missing integration.
- [ ] **Step 3: Implement** `wechat-test` and call notification processing from `capture`. Document a cron/launchd-compatible once-per-minute invocation of `python -m jd_monitor capture`; do not implement an internal endless loop.
- [ ] **Step 4: Run** `python -m pytest -q`; expect all tests pass.

### Task 5: Final Verification

**Files:** all changed files.

- [ ] **Step 1: Run** `python -m pytest -q` and `git diff --check`.
- [ ] **Step 2: Verify** no sample webhook URL, cookie, customer name, phone, address, raw order JSON, or `data/` file is tracked.
- [ ] **Step 3: Commit** the implementation with a message that states notifications occur only after eight minutes and only once after successful delivery.
