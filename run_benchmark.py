"""VehicleMemBench 评估基准的命令行入口."""

import logging
from argparse import ArgumentParser
from pathlib import Path

from vendor_adapter.VehicleMemBench.runner import prepare, report, run
from vendor_adapter.VehicleMemBench.strategies.exceptions import VehicleMemBenchError

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
    """基准测试命令行入口."""
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
        await _do_all(
            args.file_range,
            args.memory_types,
            args.reflect_num,
            allow_partial=args.allow_partial,
            output=args.output,
        )
    else:
        parser.print_help()


async def _do_all(
    file_range: str,
    memory_types: str,
    reflect_num: int,
    *,
    allow_partial: bool,
    output: Path | None,
) -> None:
    """执行 all 命令：依次运行 prepare、run、report."""
    try:
        await prepare(file_range, memory_types)
    except OSError, ValueError, RuntimeError, VehicleMemBenchError:
        logger.exception("[prepare] failed")
        if not allow_partial:
            raise
    try:
        await run(file_range, memory_types, reflect_num)
    except OSError, ValueError, RuntimeError, VehicleMemBenchError:
        logger.exception("[run] failed")
        if not allow_partial:
            raise
    report(output)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
