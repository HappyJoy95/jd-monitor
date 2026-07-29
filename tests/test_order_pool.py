import json
import os
from pathlib import Path

import pytest

import jd_monitor.order_pool as order_pool
from jd_monitor.order_pool import OrderPoolError, build_order_pool


def _record(captured_at, result_list):
    return {
        "captured_at": captured_at,
        "response": {
            "result": {
                "newOrderinfoMains": {
                    "resultList": result_list,
                }
            }
        },
    }


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_build_order_pool_aggregates_records_and_replaces_duplicate_order(tmp_path: Path):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    _write_jsonl(
        raw_path,
        [
            _record(
                "2026-07-29T08:00:00+08:00",
                [
                    {"orderId": 101, "status": "new", "obsolete": "remove me"},
                    {"orderId": "B-2", "status": "ready"},
                ],
            ),
            _record("2026-07-29T08:01:00+08:00", None),
            {"captured_at": "2026-07-29T08:02:00+08:00", "response": {}},
            _record(
                "2026-07-29T08:03:00+08:00",
                [
                    {"orderId": 101, "status": "done"},
                    {"orderId": "C-3", "status": "new"},
                ],
            ),
        ],
    )

    result = build_order_pool(raw_path, output_path)

    assert result.raw_records == 4
    assert result.unique_orders == 3
    assert result.output_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "101": {
            "first_seen_at": "2026-07-29T08:00:00+08:00",
            "order": {"orderId": 101, "status": "done"},
        },
        "B-2": {
            "first_seen_at": "2026-07-29T08:00:00+08:00",
            "order": {"orderId": "B-2", "status": "ready"},
        },
        "C-3": {
            "first_seen_at": "2026-07-29T08:03:00+08:00",
            "order": {"orderId": "C-3", "status": "new"},
        },
    }
    assert output_path.read_bytes().endswith(b"\n")


def test_blank_lines_are_ignored_and_not_counted_as_raw_records(tmp_path: Path):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    record = _record(
        "2026-07-29T08:00:00+08:00",
        [{"orderId": "A-1", "status": "new"}],
    )
    raw_path.write_text(
        "\n  \t\n" + json.dumps(record) + "\n \n",
        encoding="utf-8",
    )

    result = build_order_pool(raw_path, output_path)

    assert result.raw_records == 1
    assert result.unique_orders == 1


@pytest.mark.parametrize("alias_kind", ["direct", "dotdot", "symlink", "hardlink"])
def test_raw_and_output_must_not_refer_to_the_same_file(
    tmp_path: Path, alias_kind: str
):
    raw_path = tmp_path / "raw.jsonl"
    _write_jsonl(
        raw_path,
        [
            _record(
                "2026-07-29T08:00:00+08:00",
                [{"orderId": "A-1", "status": "private-status"}],
            )
        ],
    )
    original = raw_path.read_bytes()

    if alias_kind == "direct":
        output_path = raw_path
    elif alias_kind == "dotdot":
        (tmp_path / "alias").mkdir()
        output_path = tmp_path / "alias" / ".." / "raw.jsonl"
    elif alias_kind == "symlink":
        output_path = tmp_path / "pool-link.json"
        output_path.symlink_to(raw_path)
    else:
        output_path = tmp_path / "pool-hardlink.json"
        os.link(raw_path, output_path)

    with pytest.raises(OrderPoolError) as exc_info:
        build_order_pool(raw_path, output_path)

    assert raw_path.read_bytes() == original
    assert "private-status" not in str(exc_info.value)


@pytest.mark.parametrize("order_id", [True, False, 1.5, {}, []])
def test_order_id_rejects_non_string_and_non_integer_values(
    tmp_path: Path, order_id: object
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    original = b'{"existing":"pool"}\n'
    _write_jsonl(
        raw_path,
        [
            _record(
                "2026-07-29T08:00:00+08:00",
                [{"orderId": order_id, "status": "private-status"}],
            )
        ],
    )
    output_path.write_bytes(original)

    with pytest.raises(OrderPoolError) as exc_info:
        build_order_pool(raw_path, output_path)

    assert output_path.read_bytes() == original
    assert "private-status" not in str(exc_info.value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_constants_are_rejected_without_replacing_pool(
    tmp_path: Path, constant: str
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    original = b'{"existing":"pool"}\n'
    raw_path.write_text(
        (
            '{"captured_at":"2026-07-29T08:00:00+08:00",'
            '"response":{"result":{"newOrderinfoMains":{"resultList":'
            f'[{{"orderId":"A-1","privateValue":{constant}}}]'
            "}}}}\n"
        ),
        encoding="utf-8",
    )
    output_path.write_bytes(original)

    with pytest.raises(OrderPoolError) as exc_info:
        build_order_pool(raw_path, output_path)

    assert output_path.read_bytes() == original
    assert "privateValue" not in str(exc_info.value)


def test_non_finite_value_is_rejected_again_during_serialization(
    monkeypatch, tmp_path: Path
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    original = b'{"existing":"pool"}\n'
    raw_path.write_text("", encoding="utf-8")
    output_path.write_bytes(original)
    monkeypatch.setattr(
        order_pool,
        "_read_pool",
        lambda _: (
            1,
            {
                "A-1": {
                    "first_seen_at": "2026-07-29T08:00:00+08:00",
                    "order": {"orderId": "A-1", "value": float("nan")},
                }
            },
        ),
    )

    with pytest.raises(OrderPoolError):
        build_order_pool(raw_path, output_path)

    assert output_path.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "order_pool.json",
        "raw.jsonl",
    ]


@pytest.mark.parametrize(
    ("raw_text", "secret"),
    [
        ('{"captured_at":\n', "broken-json-secret"),
        (json.dumps(_record("", [])) + "\n", ""),
        (json.dumps(_record("not-a-date", [])) + "\n", "not-a-date"),
        (json.dumps(_record("2026-07-29T08:00:00", [])) + "\n", "2026"),
        (
            json.dumps(_record("2026-07-29T08:00:00+08:00", {"x": 1})) + "\n",
            "x",
        ),
        (
            json.dumps(_record("2026-07-29T08:00:00+08:00", ["private-order"]))
            + "\n",
            "private-order",
        ),
        (
            json.dumps(
                _record(
                    "2026-07-29T08:00:00+08:00",
                    [{"status": "secret-status"}],
                )
            )
            + "\n",
            "secret-status",
        ),
        (
            json.dumps(
                _record(
                    "2026-07-29T08:00:00+08:00",
                    [{"orderId": "", "status": "secret-status"}],
                )
            )
            + "\n",
            "secret-status",
        ),
    ],
)
def test_invalid_input_does_not_replace_existing_pool(
    tmp_path: Path, raw_text: str, secret: str
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    original = b'{"existing":"pool"}\n'
    raw_path.write_text(raw_text, encoding="utf-8")
    output_path.write_bytes(original)

    with pytest.raises(OrderPoolError) as exc_info:
        build_order_pool(raw_path, output_path)

    assert output_path.read_bytes() == original
    if secret:
        assert secret not in str(exc_info.value)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "order_pool.json",
        "raw.jsonl",
    ]


@pytest.mark.parametrize(
    "record",
    [
        {"captured_at": None},
        {"captured_at": "2026-07-29T08:00:00+08:00"},
        {
            "captured_at": "2026-07-29T08:00:00+08:00",
            "response": {"result": None},
        },
        {
            "captured_at": "2026-07-29T08:00:00+08:00",
            "response": {"result": {}},
        },
        {
            "captured_at": "2026-07-29T08:00:00+08:00",
            "response": {"result": {"newOrderinfoMains": None}},
        },
    ],
)
def test_missing_order_path_is_empty_but_captured_at_is_still_validated(
    tmp_path: Path, record: object
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    _write_jsonl(raw_path, [record])

    if record.get("captured_at") is None:
        with pytest.raises(OrderPoolError):
            build_order_pool(raw_path, output_path)
    else:
        result = build_order_pool(raw_path, output_path)
        assert result.raw_records == 1
        assert result.unique_orders == 0
        assert json.loads(output_path.read_text(encoding="utf-8")) == {}


def test_rebuild_is_byte_identical_and_leaves_no_temporary_files(tmp_path: Path):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "nested" / "order_pool.json"
    _write_jsonl(
        raw_path,
        [
            _record(
                "2026-07-29T08:00:00Z",
                [{"orderId": "订单-1", "customer": "张三"}],
            )
        ],
    )

    first_result = build_order_pool(raw_path, output_path)
    first_bytes = output_path.read_bytes()
    second_result = build_order_pool(raw_path, output_path)

    assert first_result == second_result
    assert output_path.read_bytes() == first_bytes
    assert output_path.read_text(encoding="utf-8") == (
        '{\n'
        '  "订单-1": {\n'
        '    "first_seen_at": "2026-07-29T08:00:00Z",\n'
        '    "order": {\n'
        '      "orderId": "订单-1",\n'
        '      "customer": "张三"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    assert list(output_path.parent.iterdir()) == [output_path]


def test_atomic_replace_failure_preserves_pool_and_removes_temporary_file(
    monkeypatch, tmp_path: Path
):
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "order_pool.json"
    original = b'{"existing":"pool"}\n'
    _write_jsonl(
        raw_path,
        [
            _record(
                "2026-07-29T08:00:00+08:00",
                [{"orderId": "private-order", "status": "private-status"}],
            )
        ],
    )
    output_path.write_bytes(original)

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(order_pool.os, "replace", fail_replace)

    with pytest.raises(OrderPoolError) as exc_info:
        build_order_pool(raw_path, output_path)

    assert output_path.read_bytes() == original
    assert "private-order" not in str(exc_info.value)
    assert "private-status" not in str(exc_info.value)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "order_pool.json",
        "raw.jsonl",
    ]
