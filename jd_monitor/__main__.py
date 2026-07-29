"""Command-line entry point for raw order capture and pool rebuilding."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .capture import CaptureError, OrderCapture, session_from_cookie_file
from .order_pool import OrderPoolError, build_order_pool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集京东到家订单原始响应")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="执行一次原始订单采集")
    capture.add_argument("--cookies", type=Path, default=Path("data/cookies.json"))
    capture.add_argument(
        "--output", type=Path, default=Path("data/raw_order_responses.jsonl")
    )
    pool = commands.add_parser("pool", help="从原始日志重建订单池")
    pool.add_argument(
        "--input", type=Path, default=Path("data/raw_order_responses.jsonl")
    )
    pool.add_argument("--output", type=Path, default=Path("data/order_pool.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command == "capture":
        try:
            session = session_from_cookie_file(args.cookies)
            result = OrderCapture(session, args.output).capture_once()
        except CaptureError:
            print(
                "采集失败：请检查登录状态、Cookie 文件和网络连接。",
                file=sys.stderr,
            )
            return 1

        print(f"采集完成：{result.pages} 页，{result.responses} 个响应。")
        return 0

    if args.command == "pool":
        try:
            result = build_order_pool(args.input, args.output)
        except OrderPoolError:
            print(
                "订单池更新失败：请检查原始日志格式和输出目录。",
                file=sys.stderr,
            )
            return 1

        print(
            f"订单池完成：读取 {result.raw_records} 条原始记录，"
            f"汇总 {result.unique_orders} 笔订单，已写入 {result.output_path}。"
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
