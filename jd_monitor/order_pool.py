"""Build a durable order pool from captured raw order responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any


class OrderPoolError(RuntimeError):
    """Raised when an order pool cannot be safely built and persisted."""


@dataclass(frozen=True)
class PoolBuildResult:
    raw_records: int
    unique_orders: int
    output_path: Path


def _captured_at(record: object) -> str:
    if not isinstance(record, dict):
        raise OrderPoolError("原始记录格式无效")
    value = record.get("captured_at")
    if not isinstance(value, str) or not value.strip():
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
        if not isinstance(current, dict):
            if current is None:
                return []
            raise OrderPoolError("原始记录的响应结构无效")
        if key not in current or current[key] is None:
            return []
        current = current[key]

    if not isinstance(current, dict):
        raise OrderPoolError("原始记录的响应结构无效")
    result_list = current.get("resultList")
    if result_list is None:
        return []
    if not isinstance(result_list, list):
        raise OrderPoolError("订单列表格式无效")
    return result_list


def _read_pool(raw_path: Path) -> tuple[int, dict[str, dict[str, object]]]:
    raw_records = 0
    pool: dict[str, dict[str, object]] = {}
    with raw_path.open("r", encoding="utf-8") as raw_file:
        for line in raw_file:
            if not line.strip():
                continue
            raw_records += 1
            record = json.loads(line)
            captured_at = _captured_at(record)
            for order in _orders(record):
                if not isinstance(order, dict):
                    raise OrderPoolError("订单格式无效")
                order_id = order.get("orderId")
                if order_id is None or (
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
            json.dump(pool, output, ensure_ascii=False, indent=2)
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
