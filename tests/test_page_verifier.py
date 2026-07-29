import asyncio
from datetime import datetime

import pytest

from jd_monitor.page_verifier import (
    PageStructureError,
    _launch_browser,
    build_time_window,
    normalize_dom_records,
)


def test_normalize_dom_records_returns_one_status_per_order():
    result = normalize_dom_records([
        {"orderId": "1001", "statuses": [" 待拣货 "]},
        {"orderId": "1002", "statuses": ["已完成"]},
    ])

    assert result == {"1001": "待拣货", "1002": "已完成"}


@pytest.mark.parametrize(
    "record",
    [
        {"orderId": "", "statuses": ["待拣货"]},
        {"orderId": "1001", "statuses": []},
        {"orderId": "1001", "statuses": ["待拣货", "待核验"]},
    ],
)
def test_normalize_dom_records_rejects_ambiguous_cards(record):
    with pytest.raises(PageStructureError, match="订单卡片状态结构异常"):
        normalize_dom_records([record])


def test_normalize_dom_records_rejects_duplicate_order_ids():
    with pytest.raises(PageStructureError, match="订单号重复"):
        normalize_dom_records([
            {"orderId": "1001", "statuses": ["待拣货"]},
            {"orderId": "1001", "statuses": ["待拣货"]},
        ])


def test_empty_page_is_a_valid_result():
    assert normalize_dom_records([]) == {}


def test_build_time_window_matches_api_query_window():
    assert build_time_window(datetime(2026, 7, 29, 13, 44, 53)) == {
        "dateTimeStart": "2026-07-29 00:00:00",
        "dateTimeEnd": "2026-07-29 23:59:59",
        "dateTimeStarts": "2026-07-29 00:00:00",
        "dateTimeEnds": "2026-07-29 13:44:53",
    }


def test_browser_launch_falls_back_to_installed_edge():
    calls = []
    expected_browser = object()

    class Chromium:
        async def launch(self, **options):
            calls.append(options)
            if "channel" not in options:
                raise RuntimeError("bundled browser missing")
            return expected_browser

    browser = asyncio.run(_launch_browser(Chromium(), headless=False))

    assert browser is expected_browser
    assert calls == [
        {"headless": False},
        {"headless": False, "channel": "msedge"},
    ]
