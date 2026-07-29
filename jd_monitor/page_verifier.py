"""Read final order status text from Jingdong's rendered order page."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo


PAGE_URL = (
    "https://order.jddj.com/static/web/html/pick_assistant.html?tabFlag=true"
)
ORDER_RESPONSE_PATH = "/order/newManager/tabQuery/all"
ROOT_SELECTOR = "#content-pick-box1"
CARD_SELECTOR = f"{ROOT_SELECTOR} .content-box-checkbox"
SHANGHAI = ZoneInfo("Asia/Shanghai")

EXTRACT_CARDS = """() => Array.from(
  document.querySelectorAll('#content-pick-box1 .content-box-checkbox')
).map(card => {
  const info = Array.from(card.querySelectorAll('p.comment'))
    .find(node => node.textContent.includes('订单编号：'));
  const copy = info?.querySelector('[data-clipboard-text]');
  const orderId = copy?.getAttribute('data-clipboard-text')?.trim()
    || info?.querySelector('a')?.textContent?.trim()
    || '';
  const statuses = Array.from(card.querySelectorAll('.title .time.redColor'))
    .filter(node => node.offsetParent !== null)
    .map(node => node.textContent.trim())
    .filter(Boolean);
  return {orderId, statuses};
})"""

FIRST_ORDER_ID = """() => {
  const card = document.querySelector(
    '#content-pick-box1 .content-box-checkbox'
  );
  if (!card) return '';
  const info = Array.from(card.querySelectorAll('p.comment'))
    .find(node => node.textContent.includes('订单编号：'));
  const copy = info?.querySelector('[data-clipboard-text]');
  return copy?.getAttribute('data-clipboard-text')?.trim()
    || info?.querySelector('a')?.textContent?.trim()
    || '';
}"""


class PageStructureError(RuntimeError):
    """Raised when the rendered order page cannot be read unambiguously."""


def _as_shanghai(now: datetime | None) -> datetime:
    value = now or datetime.now(SHANGHAI)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def build_time_window(now: datetime | None = None) -> dict[str, str]:
    value = _as_shanghai(now)
    start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    end = value.replace(hour=23, minute=59, second=59, microsecond=0)
    format_time = lambda item: item.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "dateTimeStart": format_time(start),
        "dateTimeEnd": format_time(end),
        "dateTimeStarts": format_time(start),
        "dateTimeEnds": format_time(value),
    }


def normalize_dom_records(records: object) -> dict[str, str]:
    if not isinstance(records, list):
        raise PageStructureError("订单页面返回结构异常")

    output: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise PageStructureError("订单卡片状态结构异常")
        order_id = str(record.get("orderId") or "").strip()
        raw_statuses = record.get("statuses")
        if not isinstance(raw_statuses, list):
            raise PageStructureError("订单卡片状态结构异常")
        statuses = [
            str(value).strip()
            for value in raw_statuses
            if str(value).strip()
        ]
        if not order_id or len(statuses) != 1:
            raise PageStructureError("订单卡片状态结构异常")
        if order_id in output:
            raise PageStructureError("订单号重复")
        output[order_id] = statuses[0]
    return output


def _read_cookies(cookie_path: Path) -> list[dict[str, object]]:
    try:
        cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PageStructureError("无法读取浏览器 Cookie 文件") from exc
    if not isinstance(cookies, list) or not all(
        isinstance(cookie, dict) for cookie in cookies
    ):
        raise PageStructureError("浏览器 Cookie 文件格式无效")
    return cookies


class JdOrderPage:
    """A visible Chromium session used only to read final DOM status text."""

    def __init__(
        self,
        cookie_path: Path | str,
        *,
        headless: bool = False,
        timeout_ms: int = 20_000,
    ):
        self.cookie_path = Path(cookie_path)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise PageStructureError("尚未安装 Playwright") from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless
            )
            self._context = await self._browser.new_context()
            await self._context.add_cookies(_read_cookies(self.cookie_path))
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            await self._page.goto(PAGE_URL, wait_until="domcontentloaded")
            await self._page.wait_for_selector(ROOT_SELECTOR)
        except Exception as exc:
            await self._close()
            if isinstance(exc, PageStructureError):
                raise
            raise PageStructureError("京东订单页面打开失败") from exc
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self._close()

    async def _close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None

    async def collect_statuses(
        self, now: datetime | None = None
    ) -> dict[str, str]:
        if self._page is None:
            raise PageStructureError("京东订单页面尚未打开")

        await self._apply_time_window(build_time_window(now))
        await self._submit_filter()
        return await self._collect_all_pages()

    async def _apply_time_window(self, window: dict[str, str]) -> None:
        for name, value in window.items():
            locator = self._page.locator(
                f'{ROOT_SELECTOR} input[name="{name}"]:visible'
            )
            if await locator.count() != 1:
                raise PageStructureError("京东页面时间筛选结构发生变化")
            await locator.fill(value)

    async def _submit_filter(self) -> None:
        button = self._page.locator(
            f"{ROOT_SELECTOR} a.ui.icon.button.blur", has_text="筛选"
        )
        if await button.count() != 1:
            raise PageStructureError("京东页面筛选按钮结构发生变化")
        try:
            async with self._page.expect_response(
                lambda response: ORDER_RESPONSE_PATH in response.url
            ) as response_info:
                await button.click()
            response = await response_info.value
            if response.status != 200:
                raise PageStructureError("京东页面订单请求失败")
            await self._wait_for_order_content()
        except PageStructureError:
            raise
        except Exception as exc:
            raise PageStructureError("京东页面筛选失败") from exc

    async def _wait_for_order_content(self) -> None:
        await self._page.wait_for_function(
            """() => {
              const root = document.querySelector('#content-pick-box1');
              return Boolean(
                root?.querySelector('.content-box-checkbox')
                || root?.querySelector('.none-data')
              );
            }"""
        )

    async def _collect_all_pages(self) -> dict[str, str]:
        all_statuses: dict[str, str] = {}
        while True:
            page_statuses = normalize_dom_records(
                await self._page.evaluate(EXTRACT_CARDS)
            )
            duplicate_ids = set(all_statuses).intersection(page_statuses)
            if duplicate_ids:
                raise PageStructureError("分页订单号重复")
            all_statuses.update(page_statuses)

            next_button = self._page.locator(
                f"{ROOT_SELECTOR} .pagination .page-next"
            )
            if await next_button.count() == 0:
                break
            classes = (await next_button.get_attribute("class")) or ""
            if "disabled" in classes.split():
                break

            previous_first_id = await self._page.evaluate(FIRST_ORDER_ID)
            try:
                async with self._page.expect_response(
                    lambda response: ORDER_RESPONSE_PATH in response.url
                ):
                    await next_button.click()
                await self._page.wait_for_function(
                    """previous => {
                      const card = document.querySelector(
                        '#content-pick-box1 .content-box-checkbox'
                      );
                      if (!card) return false;
                      const info = Array.from(card.querySelectorAll('p.comment'))
                        .find(node => node.textContent.includes('订单编号：'));
                      const copy = info?.querySelector('[data-clipboard-text]');
                      const current = copy?.getAttribute('data-clipboard-text')?.trim()
                        || info?.querySelector('a')?.textContent?.trim()
                        || '';
                      return Boolean(current && current !== previous);
                    }""",
                    previous_first_id,
                )
            except Exception as exc:
                raise PageStructureError("京东订单分页读取失败") from exc
        return all_statuses
