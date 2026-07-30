"""Capture raw responses from the Jingdong Daojia web order endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ORDER_LIST_URLS = (
    ("waitAccept", "https://order.jddj.com/order/newManager/tabQuery/waitAccept"),
    ("waitPrint", "https://order.jddj.com/order/newManager/tabQuery/waitPrint"),
    ("waitMake", "https://order.jddj.com/order/newManager/tabQuery/waitMake"),
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://order.jddj.com/static/web/html/pick_assistant.html",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0",
}


class CaptureError(RuntimeError):
    """Raised when an order-list response cannot be safely persisted."""


@dataclass(frozen=True)
class CaptureResult:
    pages: int
    responses: int
    orders: tuple[dict[str, object], ...] = ()


def session_from_cookie_file(cookie_path: Path | str) -> requests.Session:
    try:
        cookies = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CaptureError("无法读取 Cookie 文件") from exc
    if not isinstance(cookies, list):
        raise CaptureError("Cookie 文件格式无效")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie.get("path", "/"),
            )
    except (KeyError, TypeError) as exc:
        raise CaptureError("Cookie 文件格式无效") from exc
    return session


class OrderCapture:
    def __init__(self, session, output_path: Path | str):
        self.session = session
        self.output_path = Path(output_path)

    def capture_once(self, now: datetime | None = None) -> CaptureResult:
        captured_at = self._as_shanghai(now)
        pages = 0
        responses = 0
        current_orders: list[dict[str, object]] = []
        for tab, url in ORDER_LIST_URLS:
            first_request = self._request_metadata(tab, page_no=1)
            first_payload = self._fetch(url, first_request)
            page_count = self._page_count(first_payload, first_request["page_size"])
            self._append_record(captured_at, first_request, first_payload)
            current_orders.extend(self._orders(first_payload))
            pages += page_count
            responses += 1

            for page_no in range(2, page_count + 1):
                request = self._request_metadata(tab, page_no=page_no)
                payload = self._fetch(url, request)
                self._append_record(captured_at, request, payload)
                current_orders.extend(self._orders(payload))
                responses += 1
        return CaptureResult(pages=pages, responses=responses, orders=tuple(current_orders))

    @staticmethod
    def _orders(payload: object) -> list[dict[str, object]]:
        try:
            rows = payload["result"]["newOrderinfoMains"]["resultList"]
            return [row for row in rows if isinstance(row, dict)]
        except (KeyError, TypeError):
            return []

    @staticmethod
    def _as_shanghai(now: datetime | None) -> datetime:
        value = now or datetime.now(SHANGHAI)
        if value.tzinfo is None:
            return value.replace(tzinfo=SHANGHAI)
        return value.astimezone(SHANGHAI)

    @staticmethod
    def _request_metadata(tab: str, page_no: int) -> dict[str, object]:
        return {
            "tab": tab,
            "page_no": page_no,
            "page_size": 50,
        }

    def _fetch(self, url: str, request: dict[str, object]) -> object:
        try:
            response = self.session.get(
                url,
                params=self._query_params(request),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise CaptureError("订单接口请求失败") from exc
        if response.status_code != 200:
            raise CaptureError(f"订单接口返回 HTTP {response.status_code}")
        try:
            return response.json()
        except (TypeError, ValueError) as exc:
            raise CaptureError("订单接口没有返回 JSON") from exc

    @staticmethod
    def _page_count(payload: object, page_size: object) -> int:
        try:
            total_count = payload["result"]["newOrderinfoMains"]["totalCount"]
            return max(1, math.ceil(int(total_count) / int(page_size)))
        except (KeyError, TypeError, ValueError):
            return 1

    def _append_record(
        self,
        captured_at: datetime,
        request: dict[str, object],
        payload: object,
    ) -> None:
        self._append({
            "captured_at": captured_at.isoformat(),
            "request": request,
            "response": payload,
        })

    @staticmethod
    def _query_params(request: dict[str, object]) -> dict[str, object]:
        return {
            "o2oOrderType": "10000",
            "pageNo": request["page_no"],
            "pageSize": request["page_size"],
            "orderBy": "",
            "desc": "true",
        }

    def _append(self, record: dict[str, object]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")
