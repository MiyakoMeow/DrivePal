"""VehicleMemBench 评估基准的命令行入口."""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from vendor_adapter.VehicleMemBench.runner import (
    VehicleMemBenchError,
    prepare,
    report,
    run,
)

logger = logging.getLogger(__name__)


def _add_common_args(parser: ArgumentParser, default_types: str) -> None:
    parser.add_argument("--file-range", default="1-50")
    parser.add_argument("--memory-types", default=default_types)


async def _do_prepare(file_range: str, memory_types: str) -> None:
    await prepare(file_range, memory_types)


async def _do_run(file_range: str, memory_types: str, reflect_num: int = 10) -> None:
    await run(file_range, memory_types, reflect_num)


def _do_report(output: Path | None = None) -> None:
    report(output)


async def main() -> None:
    """Entry point for benchmark CLI."""
    parser = ArgumentParser(description="VehicleMemBench evaluation")
    subparsers = parser.add_subparsers(dest="command")

    _default_memory_types = "none,gold,kv,memory_bank"

    for cmd in ["prepare", "run"]:
        p = subparsers.add_parser(cmd)
        _add_common_args(p, _default_memory_types)
        if cmd == "run":
            p.add_argument("--reflect-num", type=int, default=10)

    p_all = subparsers.add_parser("all")
    _add_common_args(p_all, _default_memory_types)
    p_all.add_argument("--reflect-num", type=int, default=10)
    p_all.add_argument(
        "--allow-partial",
        action="store_true",
        default=False,
        help="Generate report even if some steps failed",
    )
    p_all.add_argument("--output", type=Path, default=None)

    rp = subparsers.add_parser("report")
    rp.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "prepare":
        await _do_prepare(args.file_range, args.memory_types)
    elif args.command == "run":
        await _do_run(args.file_range, args.memory_types, args.reflect_num)
    elif args.command == "report":
        _do_report(args.output)
    elif args.command == "all":
        failed = False
        try:
            await _do_prepare(args.file_range, args.memory_types)
        except (OSError, ValueError, RuntimeError, VehicleMemBenchError):
            logger.exception("[prepare] failed")
            failed = True
        try:
            await _do_run(args.file_range, args.memory_types, args.reflect_num)
        except (OSError, ValueError, RuntimeError, VehicleMemBenchError):
            logger.exception("[run] failed")
            failed = True
        if failed and not args.allow_partial:
            sys.stdout.write(
                "[all] aborted due to failures, skipping report (use --allow-partial to force)\n",
            )
            return
        _do_report(args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
