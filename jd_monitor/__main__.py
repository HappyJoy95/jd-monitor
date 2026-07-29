"""Command-line entry point for one-shot raw order capture."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .capture import CaptureError, OrderCapture, session_from_cookie_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集京东到家订单原始响应")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="执行一次原始订单采集")
    capture.add_argument("--cookies", type=Path, default=Path("data/cookies.json"))
    capture.add_argument(
        "--output", type=Path, default=Path("data/raw_order_responses.jsonl")
    )
    args = parser.parse_args(argv)

    if args.command != "capture":
        return 2
    try:
        session = session_from_cookie_file(args.cookies)
        result = OrderCapture(session, args.output).capture_once()
    except CaptureError:
        print("采集失败：请检查登录状态、Cookie 文件和网络连接。", file=sys.stderr)
        return 1

    print(f"采集完成：{result.pages} 页，{result.responses} 个响应。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
