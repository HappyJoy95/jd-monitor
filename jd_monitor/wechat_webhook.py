"""Safe delivery client for Enterprise WeChat robot webhooks."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


class WechatWebhookError(Exception):
    """A redacted webhook failure suitable for safe user-facing handling."""

    _MESSAGES = {
        "invalid_configuration": "Enterprise WeChat webhook configuration is invalid.",
        "network_error": "Enterprise WeChat webhook request failed.",
        "http_error": "Enterprise WeChat webhook returned an unsuccessful response.",
        "invalid_response": "Enterprise WeChat webhook returned an invalid response.",
        "business_error": "Enterprise WeChat webhook did not accept the message.",
    }

    def __init__(self, code: str):
        self.code = code
        super().__init__(self._MESSAGES[code])


def load_webhook_url(path: Path) -> str:
    """Read and validate a robot webhook URL without disclosing its secret key."""
    try:
        url = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WechatWebhookError("invalid_configuration") from exc

    parsed = urlparse(url)
    keys = parse_qs(parsed.query, keep_blank_values=True).get("key", [])
    if not (
        url
        and parsed.scheme == "https"
        and parsed.netloc == "qyapi.weixin.qq.com"
        and parsed.path == "/cgi-bin/webhook/send"
        and not parsed.params
        and not parsed.fragment
        and len(keys) == 1
        and keys[0].strip()
    ):
        raise WechatWebhookError("invalid_configuration")
    return url


class WechatWebhookClient:
    """Deliver text messages only when the Enterprise WeChat API confirms success."""

    def __init__(self, url: str):
        self.url = url

    def send_text(self, content: str) -> None:
        payload = {"msgtype": "text", "text": {"content": content}}
        try:
            response = requests.post(self.url, json=payload, timeout=15)
        except requests.RequestException as exc:
            raise WechatWebhookError("network_error") from exc

        if response.status_code != 200:
            raise WechatWebhookError("http_error")
        try:
            body = response.json()
        except (ValueError, requests.RequestException) as exc:
            raise WechatWebhookError("invalid_response") from exc
        if not isinstance(body, dict) or body.get("errcode") != 0:
            raise WechatWebhookError("business_error")
