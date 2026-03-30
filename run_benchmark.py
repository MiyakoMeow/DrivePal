"""Command-line interface for VehicleMemBench evaluation."""

import argparse


def main():
    """Entry point for benchmark CLI."""
    parser = argparse.ArgumentParser(description="VehicleMemBench evaluation")
    subparsers = parser.add_subparsers(dest="command")

    for cmd in ["prepare", "run", "all"]:
        p = subparsers.add_parser(cmd)
        p.add_argument("--file-range", default="1-50")
        p.add_argument(
            "--memory-types",
            default="gold,summary,kv,keyword,llm_only,embeddings,memory_bank",
        )
    rp = subparsers.add_parser("report")
    rp.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command in ("prepare", "run", "all"):
        from adapters.runner import prepare as do_prepare, run as do_run

    if args.command == "prepare":
        do_prepare(args.file_range, args.memory_types)
    elif args.command == "run":
        do_run(args.file_range, args.memory_types)
    elif args.command == "report":
        from adapters.runner import report as do_report

        do_report(args.output)
    elif args.command == "all":
        do_prepare(args.file_range, args.memory_types)
        do_run(args.file_range, args.memory_types)
        from adapters.runner import report as do_report

        do_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
