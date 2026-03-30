"""Command-line interface for VehicleMemBench evaluation."""

import argparse


def main():
    """Entry point for benchmark CLI."""
    parser = argparse.ArgumentParser(description="VehicleMemBench evaluation")
    subparsers = parser.add_subparsers(dest="command")

    _default_memory_types = "gold,summary,kv,keyword,llm_only,embeddings,memory_bank"

    for cmd in ["prepare", "run"]:
        p = subparsers.add_parser(cmd)
        p.add_argument("--file-range", default="1-50")
        p.add_argument("--memory-types", default=_default_memory_types)
    p_all = subparsers.add_parser("all")
    p_all.add_argument("--file-range", default="1-50")
    p_all.add_argument("--memory-types", default=_default_memory_types)
    p_all.add_argument(
        "--allow-partial",
        action="store_true",
        default=False,
        help="Generate report even if some steps failed",
    )
    rp = subparsers.add_parser("report")
    rp.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "prepare":
        from adapters.runner import prepare as do_prepare

        do_prepare(args.file_range, args.memory_types)
    elif args.command == "run":
        from adapters.runner import run as do_run

        do_run(args.file_range, args.memory_types)
    elif args.command == "report":
        from adapters.runner import report as do_report

        do_report(args.output)
    elif args.command == "all":
        failed = False
        try:
            from adapters.runner import prepare as do_prepare

            do_prepare(args.file_range, args.memory_types)
        except Exception as e:
            print(f"[prepare] failed: {e}")
            failed = True
        try:
            from adapters.runner import run as do_run

            do_run(args.file_range, args.memory_types)
        except Exception as e:
            print(f"[run] failed: {e}")
            failed = True
        if failed and not args.allow_partial:
            print(
                "[all] aborted due to failures, skipping report (use --allow-partial to force)"
            )
            return
        from adapters.runner import report as do_report

        do_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
