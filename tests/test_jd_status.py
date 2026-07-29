import pytest

from jd_monitor.jd_status import resolve_jd_status


def test_server_title_overrides_every_local_rule():
    result = resolve_jd_status({
        "sendOrderCard": {"orderStatusTitle": " 服务端状态 "},
        "stationOrderStatus": 6,
    })

    assert (result.text, result.rule_id, result.source) == (
        "服务端状态",
        "server_order_status_title",
        "server_title",
    )


@pytest.mark.parametrize(
    "prescription, expected, rule_id",
    [
        ({"useDrugName": "处方"}, "处方单待审核", "prescription_review"),
        ({"picUrlList": ["image"]}, "处方单待审核", "prescription_review"),
        ({}, "待接单", "waiting_accept"),
    ],
)
def test_station_status_16_uses_prescription_data(
    prescription, expected, rule_id
):
    result = resolve_jd_status({
        "stationOrderStatus": 16,
        "newOrderinfoExtend": {"prescriptionDTO": prescription},
    })

    assert (result.text, result.rule_id) == (expected, rule_id)


@pytest.mark.parametrize(
    "code, expected, rule_id",
    [
        (4, "配送中", "delivering"),
        (-4, "已取消", "cancelled"),
        (6, "已完成", "completed"),
        (-3, "待审核", "waiting_audit"),
        (30, "商品已送达", "goods_delivered"),
    ],
)
def test_base_statuses_match_jingdong(code, expected, rule_id):
    result = resolve_jd_status({"stationOrderStatus": code})

    assert (result.text, result.rule_id) == (expected, rule_id)


@pytest.mark.parametrize(
    "extra, expected, rule_id",
    [
        (
            {"printMark": 1, "pickMark": 1, "grabMark": 1, "businessType": 1},
            "待打印",
            "waiting_print",
        ),
        (
            {"printMark": 2, "pickMark": 1, "grabMark": 1, "businessType": 1},
            "待拣货",
            "waiting_pick",
        ),
        ({"pickMark": 2, "grabMark": 1}, "待抢单", "waiting_grab"),
        ({"pickMark": 2, "grabMark": 2}, "已抢单", "grabbed"),
        ({"pickMark": 2, "grabMark": 3}, "已收单", "received"),
        ({"pickMark": 2, "grabMark": 4}, "已完成", "grab_completed"),
        ({"pickMark": 2, "grabMark": 5}, "取消", "grab_cancelled"),
        ({"pickMark": 2, "grabMark": 6}, "取货失败", "pickup_failed"),
        (
            {"pickMark": 2, "grabMark": 7},
            "取货失败待审核",
            "pickup_failed_audit",
        ),
        ({"pickMark": 2, "grabMark": 8}, "撤销抢单", "grab_revoked"),
        ({"pickMark": 2, "grabMark": 10}, "投递失败", "delivery_failed"),
        ({"businessType": 8}, "待核验", "waiting_verification"),
        (
            {"carrierNo": 1130, "grabMark": 0},
            "召唤配送失败",
            "summon_failed",
        ),
        (
            {"carrierNo": 1130, "pickMark": 2, "grabMark": None},
            "即将召唤配送",
            "summon_pending",
        ),
    ],
)
def test_active_status_rules(extra, expected, rule_id):
    result = resolve_jd_status({"stationOrderStatus": 1, **extra})

    assert (result.text, result.rule_id) == (expected, rule_id)


@pytest.mark.parametrize("station_status", [1, 20])
def test_active_rules_apply_to_both_active_station_statuses(station_status):
    result = resolve_jd_status({
        "stationOrderStatus": station_status,
        "printMark": 1,
        "pickMark": 1,
        "grabMark": 1,
        "businessType": 1,
    })

    assert (result.text, result.rule_id) == ("待打印", "waiting_print")


@pytest.mark.parametrize("carrier", [9999, "9999"])
def test_self_pickup_accepts_numeric_and_string_carrier(carrier):
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "carrierNo": carrier,
        "businessTag": "normal",
        "pickMark": 2,
        "grabMark": -1,
    })

    assert (result.text, result.rule_id) == ("待自提", "waiting_self_pickup")


def test_a13_business_tag_excludes_self_pickup():
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "carrierNo": 9999,
        "businessTag": "prefix-A13-suffix",
        "pickMark": 2,
        "grabMark": -1,
    })

    assert result.source == "unknown"


def test_unknown_status_is_explicit_and_traceable():
    result = resolve_jd_status({"stationOrderStatus": 999})

    assert (result.text, result.rule_id, result.source) == (
        "京东未知状态",
        "unknown",
        "unknown",
    )
    assert result.ruleset_version == "pick_assistant-2026-07-29"


def test_multiple_matches_are_reported_as_conflict():
    result = resolve_jd_status({
        "stationOrderStatus": 1,
        "printMark": 2,
        "pickMark": 1,
        "grabMark": 1,
        "businessType": 8,
    })

    assert result.source == "conflict"
    assert result.text == "京东状态规则冲突"
    assert set(result.matched_rule_ids) == {
        "waiting_pick",
        "waiting_verification",
    }
