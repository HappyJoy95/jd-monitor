from pathlib import Path
from typing import Optional

import pytest
import requests

from jd_monitor.wechat_webhook import (
    WechatWebhookClient,
    WechatWebhookError,
    load_webhook_url,
)


@pytest.mark.parametrize(
    "contents",
    [None, "", "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret", "https://example.com/cgi-bin/webhook/send?key=secret", "https://qyapi.weixin.qq.com/not-webhook/send?key=secret", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"],
)
def test_load_webhook_url_rejects_invalid_configuration_without_leaking_url(
    tmp_path: Path, contents: Optional[str]
):
    path = tmp_path / "wechat_webhook.txt"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")

    with pytest.raises(WechatWebhookError) as exc_info:
        load_webhook_url(path)

    assert exc_info.value.code == "invalid_configuration"
    assert "secret" not in str(exc_info.value)
    assert "qyapi.weixin.qq.com" not in str(exc_info.value)


def test_load_webhook_url_reads_valid_url(tmp_path: Path):
    path = tmp_path / "wechat_webhook.txt"
    url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"
    path.write_text(f"  {url}\n", encoding="utf-8")

    assert load_webhook_url(path) == url


def test_send_text_posts_expected_payload_and_accepts_confirmed_success(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"errcode": 0}

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(requests, "post", fake_post)
    url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"

    WechatWebhookClient(url).send_text("new order")

    assert calls == [
        (url, {"msgtype": "text", "text": {"content": "new order"}}, 15)
    ]


@pytest.mark.parametrize(
    "failure, expected_code",
    [
        (requests.RequestException("network secret"), "network_error"),
        (500, "http_error"),
        (ValueError("json secret"), "invalid_response"),
        ({"errcode": 93000, "errmsg": "business secret"}, "business_error"),
    ],
)
def test_send_text_rejects_unconfirmed_delivery_without_leaking_details(
    monkeypatch, failure, expected_code
):
    class Response:
        def __init__(self, status_code=200, payload=None):
            self.status_code = status_code
            self.payload = payload

        def json(self):
            if isinstance(self.payload, Exception):
                raise self.payload
            return self.payload

    def fake_post(*_args, **_kwargs):
        if isinstance(failure, requests.RequestException):
            raise failure
        if isinstance(failure, int):
            return Response(status_code=failure)
        return Response(payload=failure)

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(WechatWebhookError) as exc_info:
        WechatWebhookClient(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"
        ).send_text("message")

    assert exc_info.value.code == expected_code
    assert "secret" not in str(exc_info.value)
