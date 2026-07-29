"""Compare local status decisions with the final Jingdong page text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .jd_status import resolve_jd_status


SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFE_PAGE_ERROR_CODES = {
    "browser_unavailable",
    "cookie_error",
    "login_expired",
    "page_load_error",
    "page_structure_error",
    "page_timeout",
}


@dataclass(frozen=True)
class VerificationSummary:
    total: int
    matched: int
    mismatched: int
    missing_on_page: int
    local_unknown: int
    local_conflict: int


def _verified_at(value: datetime | None) -> str:
    timestamp = value or datetime.now(SHANGHAI)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=SHANGHAI)
    else:
        timestamp = timestamp.astimezone(SHANGHAI)
    return timestamp.isoformat()


def _append_record(output_path: Path | str, record: dict[str, object]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        output.write("\n")


def orders_from_payloads(payloads: tuple[object, ...]) -> list[dict[str, object]]:
    orders: list[dict[str, object]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        main = result.get("newOrderinfoMains")
        if not isinstance(main, dict):
            continue
        result_list = main.get("resultList")
        if not isinstance(result_list, list):
            continue
        orders.extend(
            order for order in result_list if isinstance(order, dict)
        )
    return orders


def compare_and_append(
    orders: list[dict[str, object]],
    page_statuses: dict[str, str],
    output_path: Path | str,
    *,
    verified_at: datetime | None = None,
) -> VerificationSummary:
    counts = {
        "matched": 0,
        "mismatched": 0,
        "missing_on_page": 0,
        "local_unknown": 0,
        "local_conflict": 0,
    }
    timestamp = _verified_at(verified_at)

    for order in orders:
        order_id = str(order.get("orderId") or "").strip()
        status = resolve_jd_status(order)
        page_status = page_statuses.get(order_id)

        if status.source == "unknown":
            result = "local_unknown"
        elif status.source == "conflict":
            result = "local_conflict"
        elif page_status is None:
            result = "missing_on_page"
        elif status.text == page_status:
            result = "matched"
        else:
            result = "mismatched"
        counts[result] += 1

        _append_record(output_path, {
            "record_type": "order_verification",
            "verified_at": timestamp,
            "order_id": order_id,
            "local_status": status.text,
            "page_status": page_status,
            "result": result,
            "rule_id": status.rule_id,
            "source": status.source,
            "ruleset_version": status.ruleset_version,
            "status_fields": status.matched_fields,
            "matched_rule_ids": list(status.matched_rule_ids),
        })

    return VerificationSummary(total=len(orders), **counts)


def append_run_summary(
    output_path: Path | str,
    *,
    verified_at: datetime | None,
    api_orders: int,
    page_orders: int,
    matched: int,
    mismatched: int,
    missing_on_page: int,
    local_unknown: int,
    local_conflict: int,
) -> None:
    _append_record(output_path, {
        "record_type": "run_summary",
        "verified_at": _verified_at(verified_at),
        "api_orders": api_orders,
        "page_orders": page_orders,
        "matched": matched,
        "mismatched": mismatched,
        "missing_on_page": missing_on_page,
        "local_unknown": local_unknown,
        "local_conflict": local_conflict,
    })


def append_page_error(
    output_path: Path | str,
    *,
    verified_at: datetime | None,
    error_code: str,
) -> None:
    safe_code = (
        error_code if error_code in SAFE_PAGE_ERROR_CODES else "page_load_error"
    )
    _append_record(output_path, {
        "record_type": "run_error",
        "verified_at": _verified_at(verified_at),
        "result": "page_error",
        "error_code": safe_code,
    })
