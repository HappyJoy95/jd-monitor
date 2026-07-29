import json

import pytest

from jd_monitor.__main__ import build_parser, main
from jd_monitor.page_verifier import PageStructureError


def test_verify_command_defaults_to_one_shot():
    args = build_parser().parse_args(["verify"])

    assert args.command == "verify"
    assert args.interval is None


def test_verify_interval_must_be_positive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["verify", "--interval", "0"])


def test_verify_one_shot_captures_reads_compares_and_prints_counts_only(
    monkeypatch, capsys, tmp_path
):
    calls = []
    payload = {
        "result": {
            "newOrderinfoMains": {
                "resultList": [
                    {
                        "orderId": "ORDER_SECRET",
                        "stationOrderStatus": 6,
                        "fullname": "CUSTOMER_SECRET",
                    }
                ]
            }
        }
    }

    class FakeCapture:
        def __init__(self, session, output_path):
            calls.append(("capture_init", output_path))

        def capture_once(self, now=None):
            calls.append(("capture", now))

            class Result:
                pages = 1
                responses = 1
                payloads = (payload,)

            return Result()

    class FakePage:
        def __init__(self, cookie_path):
            calls.append(("page_init", cookie_path))

        async def __aenter__(self):
            calls.append(("page_enter",))
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            calls.append(("page_exit",))

        async def collect_statuses(self, now=None):
            calls.append(("page_collect", now))
            return {"ORDER_SECRET": "已完成"}

    monkeypatch.setattr("jd_monitor.__main__.session_from_cookie_file", lambda _: object())
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)
    monkeypatch.setattr("jd_monitor.__main__.JdOrderPage", FakePage)
    log_path = tmp_path / "verification.jsonl"

    exit_code = main([
        "verify",
        "--cookies",
        str(tmp_path / "cookies.json"),
        "--raw-output",
        str(tmp_path / "raw.jsonl"),
        "--log",
        str(log_path),
    ])

    assert exit_code == 0
    assert [call[0] for call in calls] == [
        "capture_init",
        "capture",
        "page_init",
        "page_enter",
        "page_collect",
        "page_exit",
    ]
    output = capsys.readouterr().out
    assert output == (
        "验证完成：1 笔，匹配 1，不一致 0，页面缺失 0，未知 0，冲突 0。\n"
    )
    assert "ORDER_SECRET" not in output
    assert "CUSTOMER_SECRET" not in output
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert records[-1]["record_type"] == "run_summary"


def test_page_failure_happens_after_raw_capture_and_logs_safe_error(
    monkeypatch, capsys, tmp_path
):
    calls = []

    class FakeCapture:
        def __init__(self, session, output_path):
            self.output_path = output_path

        def capture_once(self, now=None):
            calls.append("capture")
            self.output_path.write_text("raw-persisted\n", encoding="utf-8")

            class Result:
                payloads = ()

            return Result()

    class FailingPage:
        def __init__(self, cookie_path):
            pass

        async def __aenter__(self):
            calls.append("page")
            raise PageStructureError("COOKIE_SECRET")

        async def __aexit__(self, exc_type, exc, traceback):
            pass

    monkeypatch.setattr("jd_monitor.__main__.session_from_cookie_file", lambda _: object())
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)
    monkeypatch.setattr("jd_monitor.__main__.JdOrderPage", FailingPage)
    raw_path = tmp_path / "raw.jsonl"
    log_path = tmp_path / "verification.jsonl"

    exit_code = main([
        "verify",
        "--raw-output",
        str(raw_path),
        "--log",
        str(log_path),
    ])

    assert exit_code == 1
    assert calls == ["capture", "page"]
    assert raw_path.read_text() == "raw-persisted\n"
    combined_output = capsys.readouterr()
    assert "COOKIE_SECRET" not in combined_output.out
    assert "COOKIE_SECRET" not in combined_output.err
    error_record = json.loads(log_path.read_text())
    assert error_record["result"] == "page_error"


def test_interval_mode_reuses_one_browser_for_multiple_iterations(
    monkeypatch, capsys, tmp_path
):
    calls = []
    sleep_count = 0
    payload = {
        "result": {
            "newOrderinfoMains": {
                "resultList": [{"orderId": "1", "stationOrderStatus": 6}]
            }
        }
    }

    class FakeCapture:
        def __init__(self, session, output_path):
            pass

        def capture_once(self, now=None):
            calls.append("capture")

            class Result:
                payloads = (payload,)

            return Result()

    class FakePage:
        def __init__(self, cookie_path):
            pass

        async def __aenter__(self):
            calls.append("page_enter")
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            calls.append("page_exit")

        async def collect_statuses(self, now=None):
            calls.append("page_collect")
            return {"1": "已完成"}

    async def stop_after_two_iterations(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("jd_monitor.__main__.session_from_cookie_file", lambda _: object())
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)
    monkeypatch.setattr("jd_monitor.__main__.JdOrderPage", FakePage)
    monkeypatch.setattr("jd_monitor.__main__.asyncio.sleep", stop_after_two_iterations)

    exit_code = main([
        "verify",
        "--interval",
        "1",
        "--log",
        str(tmp_path / "verification.jsonl"),
    ])

    assert exit_code == 0
    assert calls == [
        "capture",
        "page_enter",
        "page_collect",
        "capture",
        "page_collect",
        "page_exit",
    ]
    assert capsys.readouterr().out.count("验证完成：") == 2
