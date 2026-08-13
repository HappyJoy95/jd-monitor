"""Command-line entry point for raw order capture and pool rebuilding."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .capture import CaptureError, OrderCapture, session_from_cookie_file
from .order_pool import OrderPoolError, build_current_order_pool, build_order_pool
from .notifications import process_notifications


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集京东到家订单原始响应")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="执行一次原始订单采集")
    capture.add_argument("--cookies", type=Path, default=Path("data/cookies.json"))
    capture.add_argument(
        "--output", type=Path, default=Path("data/raw_order_responses.jsonl")
    )
    capture.add_argument("--pool", type=Path, default=None)
    capture.add_argument("--webhook", type=Path, default=None)
    capture.add_argument("--no-store-notify", action="store_true", help="禁用门店群推送")
    capture.add_argument("--store-config", type=Path, default=Path("config/store_webhooks.json"), help="门店 webhook 配置文件路径")
    pool = commands.add_parser("pool", help="从原始日志重建订单池")
    pool.add_argument(
        "--input", type=Path, default=Path("data/raw_order_responses.jsonl")
    )
    pool.add_argument("--output", type=Path, default=Path("data/order_pool.json"))
    return parser


def _run_capture(args: argparse.Namespace) -> int:
    try:
        session = session_from_cookie_file(args.cookies)
        capture_result = OrderCapture(session, args.output).capture_once()
    except CaptureError:
        print(
            "采集失败：请检查登录状态、Cookie 文件和网络连接。",
            file=sys.stderr,
        )
        return 1

    pool_path = args.pool or args.output.with_name("order_pool.json")
    try:
        pool_result = build_current_order_pool(
            getattr(capture_result, "orders", ()), pool_path
        )
    except OrderPoolError:
        print(
            "采集已保存，但订单池更新失败：请检查原始日志格式和输出目录。",
            file=sys.stderr,
        )
        return 1
    main_attempted = main_sent = store_attempted = store_sent = 0
    webhook_path = args.webhook or pool_path.with_name("wechat_webhook.txt")
    if webhook_path.exists():
        try:
            store_notify = not getattr(args, "no_store_notify", False)
            main_attempted, main_sent, store_attempted, store_sent = process_notifications(
                getattr(capture_result, "orders", ()), webhook_path,
                store_notify=store_notify,
                store_configs_path=getattr(args, "store_config", None),
            )
        except Exception:
            print("采集和订单池已完成，但企微推送失败：请检查 Webhook 配置和网络。", file=sys.stderr)
            return 1

    print(
        f"采集完成：{capture_result.pages} 页，{capture_result.responses} 个响应；"
        f"订单池 {pool_result.unique_orders} 笔，已写入 {pool_result.output_path}；"
        f"主推送 {main_sent}/{main_attempted} 笔，门店推送 {store_sent}/{store_attempted} 笔。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "capture":
        return _run_capture(args)

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
