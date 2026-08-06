from pathlib import Path

from jd_monitor.sent_orders import load_sent_order_ids, mark_sent


def test_sent_orders_are_persisted(tmp_path: Path):
    path = tmp_path / "sent_orders.json"

    assert load_sent_order_ids(path) == set()
    mark_sent(path, "order-1", "2026-07-30T10:00:00+08:00")

    assert load_sent_order_ids(path) == {"order-1"}
