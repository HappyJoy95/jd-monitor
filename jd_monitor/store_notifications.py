"""Push orders to store-specific WeChat groups based on store name mapping."""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import json

from .wechat_webhook import WechatWebhookClient, load_webhook_url

SHANGHAI = ZoneInfo("Asia/Shanghai")


class StoreConfig:
    """Single store webhook configuration with business hours."""

    def __init__(self, store_name: str, start_time: str | None, end_time: str | None, webhook_url: str):
        self.store_name = store_name
        self.start_time = self._parse_time(start_time) if start_time else None
        self.end_time = self._parse_time(end_time) if end_time else None
        self.webhook_url = webhook_url

    @staticmethod
    def _parse_time(value: str) -> time:
        parts = value.split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)

    def is_within_hours(self, now: datetime) -> bool:
        current = now.astimezone(SHANGHAI) if now.tzinfo else now.replace(tzinfo=SHANGHAI)
        current_time = current.time()

        if self.start_time is None or self.end_time is None:
            return True

        if self.start_time <= self.end_time:
            return self.start_time <= current_time <= self.end_time
        else:
            return current_time >= self.start_time or current_time <= self.end_time


def load_store_configs(path: Path | str) -> list[StoreConfig]:
    config_path = Path(path)
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    configs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        store_name = item.get("门店名", "")
        webhook = item.get("webhook", "")
        if not store_name or not webhook:
            continue
        configs.append(StoreConfig(
            store_name=store_name,
            start_time=item.get("营业开始时间"),
            end_time=item.get("营业结束时间"),
            webhook_url=webhook,
        ))
    return configs


def format_store_notification(order: dict[str, object], title: str, store_name: str) -> str:
    products = order.get("listOrderinfoproduct", [])
    names = "、".join(
        str(item.get("skuName", "商品"))
        for item in products[:3]
        if isinstance(item, dict)
    ) or "商品信息待确认"
    return "{}\n门店：{}\n订单号：{}\n下单时间：{}\n商品：{}".format(
        title,
        store_name,
        order.get("o2oOrderId", order.get("orderId", "")),
        order.get("orderStartTime", ""),
        names,
    )


def format_store_config_confirmation(config: StoreConfig, platform_name: str = "京东到家订单监控") -> str:
    """Format store config confirmation message for testing."""
    start = config.start_time.strftime("%H:%M") if config.start_time else "未设置"
    end = config.end_time.strftime("%H:%M") if config.end_time else "未设置"

    return f"""【京东到家】门店推送配置确认
————————————
门店名称：{config.store_name}
营业时间：{start} ~ {end}
推送平台：{platform_name}
————————————
状态：配置完成，正常推送中"""


def send_to_store_groups(
    orders: list[tuple[dict[str, object], str]],
    configs: list[StoreConfig],
    now: datetime | None = None,
    notification_checker=None,
) -> tuple[int, int]:
    current = now or datetime.now(SHANGHAI)
    attempted = 0
    sent = 0

    config_map = {c.store_name: c for c in configs}

    for order, tab in orders:
        store_name = order.get("stationName", "")
        config = config_map.get(store_name)
        if not config:
            continue
        if not config.is_within_hours(current):
            continue
        if notification_checker:
            notification_type = notification_checker(order, current, tab)
            if not notification_type:
                continue
        else:
            notification_type = "订单提醒"

        client = WechatWebhookClient(config.webhook_url)
        try:
            client.send_text(format_store_notification(order, notification_type, store_name))
            sent += 1
        except Exception:
            pass
        attempted += 1

    return attempted, sent
