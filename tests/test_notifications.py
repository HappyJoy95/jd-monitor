from datetime import datetime
from pathlib import Path

from jd_monitor.notifications import eligible_orders, format_notification
from jd_monitor.store_notifications import StoreConfig, load_store_configs, format_store_notification, format_store_config_confirmation


def test_eligible_orders_selects_orders_within_six_minutes_of_deadline():
    pool = {
        "old": {"order": {"orderId": "old", "acceptDeadline": "2026-07-30 10:05:00"}, "tab": "waitAccept"},
        "new": {"order": {"orderId": "new", "pickDeadline": "2026-07-30 10:10:00"}, "tab": "waitPrint"},
    }

    assert eligible_orders(pool, set(), datetime(2026, 7, 30, 9, 59, 0)) == []
    assert [order["orderId"] for order, _ in eligible_orders(
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

    assert "【京东到家】待接单" in message
    assert "订单号：o2o-123" in message
    assert "状态：" not in message


def test_store_config_within_business_hours():
    config = StoreConfig("测试门店", "09:00:00", "18:00:00", "https://example.com")
    assert config.is_within_hours(datetime(2026, 7, 30, 12, 0, 0)) is True
    assert config.is_within_hours(datetime(2026, 7, 30, 8, 59, 59)) is False
    assert config.is_within_hours(datetime(2026, 7, 30, 18, 0, 1)) is False


def test_store_config_cross_midnight():
    config = StoreConfig("测试门店", "22:00:00", "06:00:00", "https://example.com")
    assert config.is_within_hours(datetime(2026, 7, 30, 23, 0, 0)) is True
    assert config.is_within_hours(datetime(2026, 7, 30, 5, 0, 0)) is True
    assert config.is_within_hours(datetime(2026, 7, 30, 12, 0, 0)) is False


def test_store_config_no_hours_always_eligible():
    config = StoreConfig("测试门店", None, None, "https://example.com")
    assert config.is_within_hours(datetime(2026, 7, 30, 12, 0, 0)) is True


def test_load_store_configs(tmp_path: Path):
    config_path = tmp_path / "store_webhooks.json"
    config_path.write_text("""[
        {
            "门店名": "测试门店",
            "营业开始时间": "09:00:00",
            "营业结束时间": "18:00:00",
            "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test123"
        }
    ]""", encoding="utf-8")

    configs = load_store_configs(config_path)
    assert len(configs) == 1
    assert configs[0].store_name == "测试门店"
    assert configs[0].webhook_url == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test123"


def test_format_store_notification():
    order = {
        "o2oOrderId": "o2o-456",
        "stationName": "测试门店",
        "orderStartTime": "2026-07-30 10:46:56",
        "listOrderinfoproduct": [{"skuName": "商品A"}, {"skuName": "商品B"}],
    }

    message = format_store_notification(order, "待接单", "测试门店")
    assert "【京东到家】待接单" in message
    assert "门店：测试门店" in message
    assert "订单号：o2o-456" in message
    assert "商品A、商品B" in message


def test_format_store_config_confirmation():
    config = StoreConfig(
        store_name="华为授权体验店（悦荟广场店）",
        start_time="09:30:00",
        end_time="22:00:00",
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test123"
    )

    message = format_store_config_confirmation(config)

    assert "【京东到家】门店推送配置确认" in message
    assert "————————————" in message
    assert "门店名称：华为授权体验店（悦荟广场店）" in message
    assert "营业时间：09:30 ~ 22:00" in message
    assert "推送平台：京东到家订单监控" in message
    assert "状态：配置完成，正常推送中" in message
