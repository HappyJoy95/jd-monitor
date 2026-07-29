"""Pure status rules mirrored from Jingdong's pick-assistant page."""

from __future__ import annotations

from dataclasses import dataclass, field


RULESET_VERSION = "pick_assistant-2026-07-29"
STATUS_FIELD_NAMES = (
    "stationOrderStatus",
    "printMark",
    "pickMark",
    "grabMark",
    "businessType",
    "carrierNo",
    "businessTag",
)


@dataclass(frozen=True)
class JdStatus:
    text: str
    rule_id: str
    source: str
    matched_fields: dict[str, object]
    ruleset_version: str = RULESET_VERSION
    matched_rule_ids: tuple[str, ...] = field(default_factory=tuple)


def _fields(order: dict[str, object]) -> dict[str, object]:
    return {name: order.get(name) for name in STATUS_FIELD_NAMES}


def _result(
    order: dict[str, object],
    text: str,
    rule_id: str,
    source: str = "local_rule",
    matched: tuple[str, ...] | list[str] = (),
) -> JdStatus:
    return JdStatus(
        text=text,
        rule_id=rule_id,
        source=source,
        matched_fields=_fields(order),
        matched_rule_ids=tuple(matched),
    )


def is_self_pickup(order: dict[str, object]) -> bool:
    """Mirror `carrierNo == 9999 && businessTag.indexOf("A13") < 0`."""

    business_tag = str(order.get("businessTag") or "")
    return str(order.get("carrierNo")) == "9999" and "A13" not in business_tag


def _resolve_active_status(order: dict[str, object]) -> JdStatus:
    if order.get("stationOrderStatus") not in (1, 20):
        return _result(order, "京东未知状态", "unknown", "unknown")

    matches: list[tuple[str, str]] = []

    def add(condition: bool, text: str, rule_id: str) -> None:
        if condition:
            matches.append((text, rule_id))

    print_mark = order.get("printMark")
    pick_mark = order.get("pickMark")
    grab_mark = order.get("grabMark")
    business_type = order.get("businessType")
    carrier = str(order.get("carrierNo"))

    add(
        print_mark == 1
        and pick_mark == 1
        and grab_mark != 0
        and business_type not in (8, 9),
        "待打印",
        "waiting_print",
    )
    add(
        isinstance(print_mark, (int, float))
        and print_mark > 1
        and pick_mark == 1
        and grab_mark != 0,
        "待拣货",
        "waiting_pick",
    )

    grab_statuses = {
        1: ("待抢单", "waiting_grab"),
        2: ("已抢单", "grabbed"),
        3: ("已收单", "received"),
        4: ("已完成", "grab_completed"),
        5: ("取消", "grab_cancelled"),
        6: ("取货失败", "pickup_failed"),
        7: ("取货失败待审核", "pickup_failed_audit"),
        8: ("撤销抢单", "grab_revoked"),
        10: ("投递失败", "delivery_failed"),
    }
    if pick_mark == 2 and grab_mark in grab_statuses:
        matches.append(grab_statuses[grab_mark])

    add(business_type == 8, "待核验", "waiting_verification")
    add(
        is_self_pickup(order) and pick_mark == 2 and grab_mark != 0,
        "待自提",
        "waiting_self_pickup",
    )
    add(
        carrier == "1130" and grab_mark == 0,
        "召唤配送失败",
        "summon_failed",
    )
    add(
        carrier == "1130" and pick_mark == 2 and grab_mark is None,
        "即将召唤配送",
        "summon_pending",
    )

    if not matches:
        return _result(order, "京东未知状态", "unknown", "unknown")
    if len(matches) > 1:
        return _result(
            order,
            "京东状态规则冲突",
            "conflict",
            "conflict",
            [rule_id for _, rule_id in matches],
        )
    text, rule_id = matches[0]
    return _result(order, text, rule_id)


def resolve_jd_status(order: dict[str, object]) -> JdStatus:
    card = order.get("sendOrderCard") or {}
    if isinstance(card, dict):
        title = card.get("orderStatusTitle")
        if isinstance(title, str) and title.strip():
            return _result(
                order,
                title.strip(),
                "server_order_status_title",
                "server_title",
            )

    station_status = order.get("stationOrderStatus")
    if station_status == 16:
        extension = order.get("newOrderinfoExtend") or {}
        prescription = (
            extension.get("prescriptionDTO") if isinstance(extension, dict) else {}
        ) or {}
        has_prescription = isinstance(prescription, dict) and bool(
            prescription.get("useDrugName") or prescription.get("picUrlList")
        )
        return _result(
            order,
            "处方单待审核" if has_prescription else "待接单",
            "prescription_review" if has_prescription else "waiting_accept",
        )

    base_statuses = {
        4: ("配送中", "delivering"),
        -4: ("已取消", "cancelled"),
        6: ("已完成", "completed"),
        -3: ("待审核", "waiting_audit"),
        30: ("商品已送达", "goods_delivered"),
    }
    if station_status in base_statuses:
        text, rule_id = base_statuses[station_status]
        return _result(order, text, rule_id)
    return _resolve_active_status(order)
