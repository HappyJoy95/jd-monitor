"""Build a durable order pool from captured raw order responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


CAPTURED_AT_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?"
    r"[+-](?:[01][0-9]|2[0-3]):[0-5][0-9]"
)


class OrderPoolError(RuntimeError):
    """Raised when an order pool cannot be safely built and persisted."""


@dataclass(frozen=True)
class PoolBuildResult:
    raw_records: int
    unique_orders: int
    output_path: Path


def _reject_non_finite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _captured_at(record: object) -> str:
    if not isinstance(record, dict):
        raise OrderPoolError("原始记录格式无效")
    value = record.get("captured_at")
    if not isinstance(value, str) or not value.strip():
        raise OrderPoolError("原始记录的采集时间无效")
    if CAPTURED_AT_PATTERN.fullmatch(value) is None:
        raise OrderPoolError("原始记录的采集时间无效")
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
    except (TypeError, ValueError, OverflowError) as exc:
        raise OrderPoolError("原始记录的采集时间无效") from exc
    if parsed.tzinfo is None or offset is None:
        raise OrderPoolError("原始记录的采集时间缺少时区")
    return value


def _orders(record: dict[str, Any]) -> list[object]:
    current: object = record
    for key in ("response", "result", "newOrderinfoMains"):
        if not isinstance(current, dict) or key not in current:
            raise OrderPoolError("原始记录的响应结构无效")
        current = current[key]

    if not isinstance(current, dict):
        raise OrderPoolError("原始记录的响应结构无效")
    if "resultList" not in current:
        raise OrderPoolError("订单列表格式无效")
    result_list = current["resultList"]
    if not isinstance(result_list, list):
        raise OrderPoolError("订单列表格式无效")
    return result_list


def _read_pool(raw_path: Path) -> tuple[int, dict[str, dict[str, object]]]:
    raw_records = 0
    pool: dict[str, dict[str, object]] = {}
    with raw_path.open("r", encoding="utf-8") as raw_file:
        for line in raw_file:
            if not line.strip():
                raise OrderPoolError("原始记录包含空白行")
            raw_records += 1
            record = json.loads(line, parse_constant=_reject_non_finite)
            captured_at = _captured_at(record)
            for order in _orders(record):
                if not isinstance(order, dict):
                    raise OrderPoolError("订单格式无效")
                order_id = order.get("orderId")
                if type(order_id) not in (str, int) or (
                    isinstance(order_id, str) and not order_id.strip()
                ):
                    raise OrderPoolError("订单编号无效")
                key = str(order_id)
                if key in pool:
                    pool[key]["order"] = order
                else:
                    pool[key] = {
                        "first_seen_at": captured_at,
                        "order": order,
                    }
    return raw_records, pool


def _atomic_write(output_path: Path, pool: dict[str, dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            json.dump(pool, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def build_order_pool(
    raw_path: Path | str,
    output_path: Path | str,
) -> PoolBuildResult:
    """Aggregate raw JSONL records and atomically replace the order pool."""

    raw = Path(raw_path)
    output = Path(output_path)
    try:
        raw_records, pool = _read_pool(raw)
        try:
            same_file = os.path.samefile(raw, output)
        except FileNotFoundError:
            same_file = False
        if same_file:
            raise OrderPoolError("原始记录与订单池路径不能指向同一文件")
        _atomic_write(output, pool)
    except OrderPoolError:
        raise
    except Exception as exc:
        raise OrderPoolError("无法构建订单池") from exc
    return PoolBuildResult(
        raw_records=raw_records,
        unique_orders=len(pool),
        output_path=output,
    )


def build_current_order_pool(
    orders: list[tuple[dict[str, object], str]] | tuple[tuple[dict[str, object], str], ...],
    output_path: Path | str,
) -> PoolBuildResult:
    """Replace the pool with orders observed in the current capture only."""
    now = datetime.now().astimezone().isoformat()
    pool: dict[str, dict[str, object]] = {}
    for order, tab in orders:
        order_id = order.get("orderId")
        if type(order_id) not in (str, int) or not str(order_id).strip():
            continue
        pool[str(order_id)] = {"first_seen_at": now, "order": order, "tab": tab}
    output = Path(output_path)
    try:
        _atomic_write(output, pool)
    except Exception as exc:
        raise OrderPoolError("无法构建实时订单池") from exc
    return PoolBuildResult(raw_records=0, unique_orders=len(pool), output_path=output)
