from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from jd_monitor.capture import OrderCapture, session_from_cookie_file
from jd_monitor.__main__ import main


def test_capture_appends_unmodified_response_with_request_metadata(tmp_path: Path):
    captured: list[dict] = []

    class Response:
        status_code = 200

        def json(self):
            return {"code": "0", "result": {"orders": ["unchanged"]}}

    class Session:
        def get(self, url, *, params, timeout):
            captured.append({"url": url, "params": params, "timeout": timeout})
            return Response()

    output = tmp_path / "raw_order_responses.jsonl"
    result = OrderCapture(Session(), output).capture_once(
        now=datetime(2026, 7, 29, 13, 44, 53)
    )

    assert result.pages == 1
    assert result.responses == 1
    assert captured[0]["params"]["endTimeQuery"] == "2026-07-29 13:44:53"
    assert output.read_text(encoding="utf-8").splitlines() == [
        '{"captured_at":"2026-07-29T13:44:53+08:00","request":{"page_no":1,"page_size":50,"start_time_query":"2026-07-29 00:00:00","end_time_query":"2026-07-29 13:44:53","pre_start_delivery_time":"2026-07-29 00:00:00","pre_end_delivery_time":"2026-07-29 23:59:59","station_no":""},"response":{"code":"0","result":{"orders":["unchanged"]}}}'
    ]


def test_session_from_cookie_file_loads_playwright_cookies(tmp_path: Path):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(
        '[{"name":"thor","value":"secret","domain":"order.jddj.com","path":"/"}]',
        encoding="utf-8",
    )

    session = session_from_cookie_file(cookie_path)

    assert session.cookies.get("thor", domain="order.jddj.com", path="/") == "secret"


def test_capture_writes_each_page_when_total_count_requires_pagination(tmp_path: Path):
    payloads = [
        {"code": "0", "result": {"newOrderinfoMains": {"totalCount": 51}}},
        {"code": "0", "result": {"newOrderinfoMains": {"totalCount": 51}}},
    ]

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls: list[dict] = []

        def get(self, url, *, params, timeout):
            self.calls.append({"url": url, "params": params, "timeout": timeout})
            return Response(payloads[len(self.calls) - 1])

    session = Session()
    output = tmp_path / "raw.jsonl"
    result = OrderCapture(session, output).capture_once(
        now=datetime(2026, 7, 29, 13, 44, 53)
    )

    assert result.pages == 2
    assert result.responses == 2
    assert [call["params"]["pageNo"] for call in session.calls] == [1, 2]
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_main_capture_reports_counts_without_response_or_cookie_content(
    monkeypatch, capsys, tmp_path: Path
):
    pool_path = tmp_path / "pool.json"

    class FakeCapture:
        def __init__(self, session, output_path):
            assert session is not None
            assert output_path == tmp_path / "raw.jsonl"

        def capture_once(self):
            class Result:
                pages = 2
                responses = 2

            return Result()

    monkeypatch.setattr("jd_monitor.__main__.session_from_cookie_file", lambda _: object())
    monkeypatch.setattr("jd_monitor.__main__.OrderCapture", FakeCapture)
    monkeypatch.setattr(
        "jd_monitor.__main__.build_order_pool",
        lambda raw_path, output_path: SimpleNamespace(
            unique_orders=3,
            output_path=output_path,
        ),
    )

    exit_code = main([
        "capture",
        "--cookies", str(tmp_path / "cookies.json"),
        "--output", str(tmp_path / "raw.jsonl"),
        "--pool", str(pool_path),
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == (
        f"采集完成：2 页，2 个响应；订单池 3 笔，已写入 {pool_path}。\n"
    )
    assert captured.err == ""
