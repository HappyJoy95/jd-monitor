"""Command-line entry points for raw capture and status verification."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sys

from .capture import (
    CaptureError,
    OrderCapture,
    SHANGHAI,
    session_from_cookie_file,
)
from .page_verifier import JdOrderPage, PageStructureError
from .verification import (
    append_page_error,
    append_run_summary,
    compare_and_append,
    orders_from_payloads,
)


def positive_seconds(value: str) -> int:
    seconds = int(value)
    if seconds < 1:
        raise argparse.ArgumentTypeError("interval must be positive")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集并验证京东订单状态")
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="执行一次原始订单采集")
    capture.add_argument(
        "--cookies", type=Path, default=Path("data/cookies.json")
    )
    capture.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw_order_responses.jsonl"),
    )

    verify = commands.add_parser("verify", help="对照京东页面验证本地状态")
    verify.add_argument(
        "--cookies", type=Path, default=Path("data/cookies.json")
    )
    verify.add_argument(
        "--raw-output",
        type=Path,
        default=Path("data/raw_order_responses.jsonl"),
    )
    verify.add_argument(
        "--log",
        type=Path,
        default=Path("data/status_verification.jsonl"),
    )
    verify.add_argument("--interval", type=positive_seconds)
    return parser


def _run_capture(args: argparse.Namespace) -> int:
    session = session_from_cookie_file(args.cookies)
    result = OrderCapture(session, args.output).capture_once()
    print(f"采集完成：{result.pages} 页，{result.responses} 个响应。")
    return 0


async def _close_page(page_reader) -> None:
    if page_reader is not None:
        await page_reader.__aexit__(None, None, None)


async def _run_verify(args: argparse.Namespace) -> int:
    session = session_from_cookie_file(args.cookies)
    capture = OrderCapture(session, args.raw_output)
    page_reader = None

    try:
        while True:
            verified_at = datetime.now(SHANGHAI)
            try:
                capture_result = await asyncio.to_thread(
                    capture.capture_once, now=verified_at
                )
            except CaptureError:
                print(
                    "采集失败：请检查登录状态、Cookie 文件和网络连接。",
                    file=sys.stderr,
                )
                if args.interval is None:
                    return 1
                await asyncio.sleep(args.interval)
                continue

            if page_reader is None:
                candidate = JdOrderPage(args.cookies)
                try:
                    page_reader = await candidate.__aenter__()
                except PageStructureError:
                    append_page_error(
                        args.log,
                        verified_at=verified_at,
                        error_code="page_structure_error",
                    )
                    print(
                        "页面验证失败：请检查登录状态、浏览器组件和页面结构。",
                        file=sys.stderr,
                    )
                    if args.interval is None:
                        return 1
                    await asyncio.sleep(args.interval)
                    continue

            try:
                page_statuses = await page_reader.collect_statuses(
                    now=verified_at
                )
            except PageStructureError:
                append_page_error(
                    args.log,
                    verified_at=verified_at,
                    error_code="page_structure_error",
                )
                print(
                    "页面验证失败：请检查登录状态和页面结构。",
                    file=sys.stderr,
                )
                await _close_page(page_reader)
                page_reader = None
                if args.interval is None:
                    return 1
                await asyncio.sleep(args.interval)
                continue

            orders = orders_from_payloads(capture_result.payloads)
            summary = compare_and_append(
                orders,
                page_statuses,
                args.log,
                verified_at=verified_at,
            )
            append_run_summary(
                args.log,
                verified_at=verified_at,
                api_orders=summary.total,
                page_orders=len(page_statuses),
                matched=summary.matched,
                mismatched=summary.mismatched,
                missing_on_page=summary.missing_on_page,
                local_unknown=summary.local_unknown,
                local_conflict=summary.local_conflict,
            )
            print(
                f"验证完成：{summary.total} 笔，"
                f"匹配 {summary.matched}，"
                f"不一致 {summary.mismatched}，"
                f"页面缺失 {summary.missing_on_page}，"
                f"未知 {summary.local_unknown}，"
                f"冲突 {summary.local_conflict}。"
            )

            if args.interval is None:
                return 0
            await asyncio.sleep(args.interval)
    finally:
        await _close_page(page_reader)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            return _run_capture(args)
        if args.command == "verify":
            return asyncio.run(_run_verify(args))
    except CaptureError:
        print(
            "采集失败：请检查登录状态、Cookie 文件和网络连接。",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("验证已停止。")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
