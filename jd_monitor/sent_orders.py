"""Persist only IDs of orders whose notifications were delivered."""

from __future__ import annotations

import json
from pathlib import Path


class SentOrdersError(RuntimeError):
    """Raised when the local sent-order ledger cannot be used."""


def _read(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SentOrdersError("无法读取已推送订单记录") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SentOrdersError("已推送订单记录格式无效")
    return value


def load_sent_order_ids(path: Path | str) -> set[str]:
    return set(_read(Path(path)))


def mark_sent(path: Path | str, order_id: str, sent_at: str) -> None:
    ledger_path = Path(path)
    records = _read(ledger_path)
    records[order_id] = {"sent_at": sent_at}
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise SentOrdersError("无法写入已推送订单记录") from exc
