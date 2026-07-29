from pathlib import Path
from types import SimpleNamespace

from jd_monitor import __main__ as cli
from jd_monitor.order_pool import OrderPoolError


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


def test_unknown_command_returns_two(capsys):
    assert cli.main(["unknown"]) == 2
    assert "unknown" not in capsys.readouterr().out
