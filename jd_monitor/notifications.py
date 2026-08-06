"""Select active orders that have waited long enough for notification."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pathlib import Path
import json

from .wechat_webhook import WechatWebhookClient, load_webhook_url


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEADLINE_WINDOW_SECONDS = 6 * 60


def eligible_orders(
    pool: dict[str, object], sent_order_ids: set[str], now: datetime
) -> list[tuple[dict[str, object], str]]:
    current = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)
    eligible: list[tuple[dict[str, object], str]] = []
    for entry in pool.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("order"), dict):
            continue
        order = entry["order"]
        tab = entry.get("tab", "")
        order_id = str(order.get("orderId", ""))
        if not order_id:
            continue
        if notification_type(order, current, tab) is not None:
            eligible.append((order, tab))
    return eligible


def _deadline(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    except ValueError:
        return None


def notification_type(order: dict[str, object], now: datetime, tab: str = "") -> str | None:
    current = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)
    if tab == "waitAccept":
        field, title = "acceptDeadline", "待接单"
        value = order.get(field)
        deadline = _deadline(value)
        if deadline is not None and 0 < (deadline - current).total_seconds() < DEADLINE_WINDOW_SECONDS:
            return title
    elif tab == "waitPrint":
        field, title = "pickDeadline", "待拣货"
        value = order.get(field) or order.get("newOrderinfoExtend", {}).get(field)
        deadline = _deadline(value)
        if deadline is not None and 0 < (deadline - current).total_seconds() < DEADLINE_WINDOW_SECONDS:
            return title
    return None


def format_notification(order: dict[str, object], title: str) -> str:
    products = order.get("listOrderinfoproduct", [])
    names = "、".join(
        str(item.get("skuName", "商品"))
        for item in products[:3]
        if isinstance(item, dict)
    ) or "商品信息待确认"
    return "{}\n订单号：{}\n门店：{}\n下单时间：{}\n商品：{}".format(
        title,
        order.get("o2oOrderId", order.get("orderId", "")),
        order.get("stationName", ""),
        order.get("orderStartTime", ""),
        names,
    )


def process_notifications(orders: list[tuple[dict[str, object], str]] | tuple[dict[str, object], str], webhook_path: Path | str, now: datetime | None = None) -> tuple[int, int]:
    current = now or datetime.now(SHANGHAI)
    pool = {str(index): {"order": order, "tab": tab} for index, (order, tab) in enumerate(orders)}
    eligible = eligible_orders(pool, set(), current)
    client = WechatWebhookClient(load_webhook_url(Path(webhook_path)))
    for order, tab in eligible:
        client.send_text(format_notification(order, notification_type(order, current, tab) or "订单提醒"))
    return len(eligible), len(eligible)
