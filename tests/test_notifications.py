from datetime import datetime
from pathlib import Path

from jd_monitor.notifications import eligible_orders, format_notification


def test_eligible_orders_selects_orders_within_six_minutes_of_deadline():
    pool = {
        "old": {"order": {"orderId": "old", "acceptDeadline": "2026-07-30 10:05:00"}},
        "new": {"order": {"orderId": "new", "pickDeadline": "2026-07-30 10:10:00"}},
    }

    assert eligible_orders(pool, set(), datetime(2026, 7, 30, 9, 59, 0)) == []
    assert [order["orderId"] for order in eligible_orders(
        pool, set(), datetime(2026, 7, 30, 10, 0, 1)
    )] == ["old"]


def test_notification_uses_o2o_order_id_and_omits_status_number():
    message = format_notification({
        "orderId": "1",
        "o2oOrderId": "o2o-123",
        "stationName": "门店",
        "stationOrderStatus": "16",
        "orderStartTime": "2026-07-30 10:46:56",
        "listOrderinfoproduct": [{"skuName": "商品"}],
    }, "待接单")

    assert "订单号：o2o-123" in message
    assert "状态：" not in message
