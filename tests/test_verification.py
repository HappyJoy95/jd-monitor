import json
from datetime import datetime

from jd_monitor.verification import (
    append_page_error,
    append_run_summary,
    compare_and_append,
    orders_from_payloads,
)


def test_orders_from_payloads_flattens_api_pages():
    payloads = (
        {"result": {"newOrderinfoMains": {"resultList": [{"orderId": "1"}]}}},
        {"result": {"newOrderinfoMains": {"resultList": [{"orderId": "2"}]}}},
    )

    assert orders_from_payloads(payloads) == [
        {"orderId": "1"},
        {"orderId": "2"},
    ]


def test_compare_and_append_records_match_mismatch_and_missing_without_pii(
    tmp_path,
):
    orders = [
        {
            "orderId": "1",
            "stationOrderStatus": 6,
            "fullname": "secret-name",
        },
        {
            "orderId": "2",
            "stationOrderStatus": 4,
            "mobile": "secret-phone",
        },
        {
            "orderId": "3",
            "stationOrderStatus": 30,
            "fullAddress": "secret-address",
        },
    ]
    output = tmp_path / "verification.jsonl"

    summary = compare_and_append(
        orders,
        {"1": "已完成", "2": "已完成"},
        output,
        verified_at=datetime(2026, 7, 29, 15, 0, 0),
    )

    assert (
        summary.matched,
        summary.mismatched,
        summary.missing_on_page,
    ) == (1, 1, 1)
    text = output.read_text(encoding="utf-8")
    assert "secret-name" not in text
    assert "secret-phone" not in text
    assert "secret-address" not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert [record["result"] for record in records] == [
        "matched",
        "mismatched",
        "missing_on_page",
    ]
    assert records[0]["verified_at"] == "2026-07-29T15:00:00+08:00"
    assert set(records[0]) == {
        "record_type",
        "verified_at",
        "order_id",
        "local_status",
        "page_status",
        "result",
        "rule_id",
        "source",
        "ruleset_version",
        "status_fields",
        "matched_rule_ids",
    }


def test_local_unknown_and_conflict_take_priority_over_page_comparison(tmp_path):
    orders = [
        {"orderId": "1", "stationOrderStatus": 999},
        {
            "orderId": "2",
            "stationOrderStatus": 1,
            "printMark": 2,
            "pickMark": 1,
            "grabMark": 1,
            "businessType": 8,
        },
    ]
    output = tmp_path / "verification.jsonl"

    summary = compare_and_append(
        orders,
        {"1": "已完成", "2": "待核验"},
        output,
        verified_at=datetime(2026, 7, 29, 15, 0, 0),
    )

    assert (summary.local_unknown, summary.local_conflict) == (1, 1)
    assert [json.loads(line)["result"] for line in output.read_text().splitlines()] == [
        "local_unknown",
        "local_conflict",
    ]


def test_run_summary_and_page_error_contain_counts_and_safe_code_only(tmp_path):
    output = tmp_path / "verification.jsonl"
    verified_at = datetime(2026, 7, 29, 15, 0, 0)

    append_run_summary(
        output,
        verified_at=verified_at,
        api_orders=5,
        page_orders=5,
        matched=5,
        mismatched=0,
        missing_on_page=0,
        local_unknown=0,
        local_conflict=0,
    )
    append_page_error(
        output,
        verified_at=verified_at,
        error_code="page_structure_error",
    )

    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert records[0]["record_type"] == "run_summary"
    assert records[0]["matched"] == 5
    assert records[1] == {
        "record_type": "run_error",
        "verified_at": "2026-07-29T15:00:00+08:00",
        "result": "page_error",
        "error_code": "page_structure_error",
    }
