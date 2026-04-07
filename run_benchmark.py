"""Command-line interface for VehicleMemBench evaluation."""

import argparse
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path


def _add_common_args(parser: argparse.ArgumentParser, default_types: str) -> None:
    parser.add_argument("--file-range", default="1-50")
    parser.add_argument("--memory-types", default=default_types)


async def _do_prepare(file_range: str, memory_types: str) -> None:
    from vendor_adapter.VehicleMemBench.runner import prepare

    await prepare(file_range, memory_types)


async def _do_run(file_range: str, memory_types: str) -> None:
    from vendor_adapter.VehicleMemBench.runner import run

    await run(file_range, memory_types)


def _do_report(output: Optional[Path] = None) -> None:
    from vendor_adapter.VehicleMemBench.runner import report

    report(output)


async def main() -> None:
    """Entry point for benchmark CLI."""
    parser = argparse.ArgumentParser(description="VehicleMemBench evaluation")
    subparsers = parser.add_subparsers(dest="command")

    _default_memory_types = "gold,summary,kv,memory_bank"

    for cmd in ["prepare", "run"]:
        _add_common_args(subparsers.add_parser(cmd), _default_memory_types)

    p_all = subparsers.add_parser("all")
    _add_common_args(p_all, _default_memory_types)
    p_all.add_argument(
        "--allow-partial",
        action="store_true",
        default=False,
        help="Generate report even if some steps failed",
    )
    p_all.add_argument("--output", default=None)

    rp = subparsers.add_parser("report")
    rp.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "prepare":
        await _do_prepare(args.file_range, args.memory_types)
    elif args.command == "run":
        await _do_run(args.file_range, args.memory_types)
    elif args.command == "report":
        _do_report(args.output)
    elif args.command == "all":
        failed = False
        try:
            await _do_prepare(args.file_range, args.memory_types)
        except Exception as e:
            print(f"[prepare] failed: {e}")
            failed = True
        try:
            await _do_run(args.file_range, args.memory_types)
        except Exception as e:
            print(f"[run] failed: {e}")
            failed = True
        if failed and not args.allow_partial:
            print(
                "[all] aborted due to failures, skipping report (use --allow-partial to force)"
            )
            return
        _do_report(args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
