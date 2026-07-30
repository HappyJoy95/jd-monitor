from pathlib import Path
from types import SimpleNamespace

import pytest

from jd_monitor import __main__ as cli
from jd_monitor.capture import CaptureError
from jd_monitor.order_pool import OrderPoolError


def test_capture_parser_preserves_default_paths():
    args = cli.build_parser().parse_args(["capture"])

    assert args.cookies == Path("data/cookies.json")
    assert args.output == Path("data/raw_order_responses.jsonl")
    assert args.pool is None


def test_capture_refreshes_explicit_pool_after_capture(monkeypatch, tmp_path: Path):
    raw_path = tmp_path / "raw.jsonl"
    pool_path = tmp_path / "custom-pool.json"
    calls = []

    class FakeCapture:
        def __init__(self, _session, output_path):
            assert output_path == raw_path

        def capture_once(self):
            calls.append(("capture", raw_path))
            return SimpleNamespace(pages=2, responses=2)

    def fake_build_current_order_pool(orders, output_path):
        calls.append(("pool", orders, output_path))
        return SimpleNamespace(unique_orders=4, output_path=output_path)

    monkeypatch.setattr(cli, "session_from_cookie_file", lambda _: object())
    monkeypatch.setattr(cli, "OrderCapture", FakeCapture)
    monkeypatch.setattr(cli, "build_current_order_pool", fake_build_current_order_pool)

    assert cli.main([
        "capture",
        "--output",
        str(raw_path),
        "--pool",
        str(pool_path),
    ]) == 0
    assert calls == [
        ("capture", raw_path),
        ("pool", (), pool_path),
    ]


def test_capture_defaults_pool_to_raw_file_directory(monkeypatch, tmp_path: Path):
    raw_path = tmp_path / "custom" / "events.jsonl"
    calls = []

    class FakeCapture:
        def __init__(self, _session, _output_path):
            pass

        def capture_once(self):
            return SimpleNamespace(pages=1, responses=1)

    def fake_build_current_order_pool(orders, output_path):
        calls.append((orders, output_path))
        return SimpleNamespace(unique_orders=0, output_path=output_path)

    monkeypatch.setattr(cli, "session_from_cookie_file", lambda _: object())
    monkeypatch.setattr(cli, "OrderCapture", FakeCapture)
    monkeypatch.setattr(cli, "build_current_order_pool", fake_build_current_order_pool)

    assert cli.main(["capture", "--output", str(raw_path)]) == 0
    assert calls == [((), raw_path.with_name("order_pool.json"))]


def test_capture_pool_error_preserves_raw_log_and_hides_details(
    monkeypatch, capsys, tmp_path: Path
):
    raw_path = tmp_path / "raw.jsonl"

    class FakeCapture:
        def __init__(self, _session, output_path):
            self.output_path = output_path

        def capture_once(self):
            self.output_path.write_text("saved raw\n", encoding="utf-8")
            return SimpleNamespace(pages=1, responses=1)

    def fail_pool(_orders, _output_path):
        raise OrderPoolError("SECRET")

    monkeypatch.setattr(cli, "session_from_cookie_file", lambda _: object())
    monkeypatch.setattr(cli, "OrderCapture", FakeCapture)
    monkeypatch.setattr(cli, "build_current_order_pool", fail_pool)

    assert cli.main(["capture", "--output", str(raw_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "采集已保存，但订单池更新失败：请检查原始日志格式和输出目录。\n"
    )
    assert "SECRET" not in captured.err
    assert raw_path.read_text(encoding="utf-8") == "saved raw\n"


def test_capture_error_does_not_refresh_pool(monkeypatch, capsys):
    class FakeCapture:
        def __init__(self, _session, _output_path):
            pass

        def capture_once(self):
            raise CaptureError("SECRET")

    pool_called = False

    def build_pool_should_not_run(_input_path, _output_path):
        nonlocal pool_called
        pool_called = True

    monkeypatch.setattr(cli, "session_from_cookie_file", lambda _: object())
    monkeypatch.setattr(cli, "OrderCapture", FakeCapture)
    monkeypatch.setattr(cli, "build_order_pool", build_pool_should_not_run)

    assert cli.main(["capture"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "采集失败：请检查登录状态、Cookie 文件和网络连接。\n"
    assert "SECRET" not in captured.err
    assert pool_called is False


def test_pool_parser_uses_default_paths():
    args = cli.build_parser().parse_args(["pool"])

    assert args.input == Path("data/raw_order_responses.jsonl")
    assert args.output == Path("data/order_pool.json")


def test_pool_passes_explicit_paths_to_builder(monkeypatch, tmp_path: Path):
    input_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "pool.json"
    calls = []

    def fake_build_order_pool(raw_path, pool_path):
        calls.append((raw_path, pool_path))
        return SimpleNamespace(
            raw_records=0,
            unique_orders=0,
            output_path=pool_path,
        )

    monkeypatch.setattr(cli, "build_order_pool", fake_build_order_pool)

    assert cli.main([
        "pool",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]) == 0
    assert calls == [(input_path, output_path)]


def test_pool_success_prints_only_counts_and_output_path(
    monkeypatch, capsys, tmp_path: Path
):
    output_path = tmp_path / "pool.json"
    monkeypatch.setattr(
        cli,
        "build_order_pool",
        lambda _input, _output: SimpleNamespace(
            raw_records=7,
            unique_orders=3,
            output_path=output_path,
        ),
    )

    assert cli.main(["pool"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        f"订单池完成：读取 7 条原始记录，汇总 3 笔订单，已写入 {output_path}。\n"
    )
    assert captured.err == ""


def test_pool_error_returns_one_without_leaking_details(monkeypatch, capsys):
    def fail(_input, _output):
        raise OrderPoolError("SECRET")

    monkeypatch.setattr(cli, "build_order_pool", fail)

    assert cli.main(["pool"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "订单池更新失败：请检查原始日志格式和输出目录。\n"
    assert "SECRET" not in captured.err


def test_unknown_command_exits_with_status_two():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["unknown"])

    assert exc_info.value.code == 2
