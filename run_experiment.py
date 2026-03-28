#!/usr/bin/env python3
"""实验 Pipeline CLI：prepare -> run -> judge."""

import argparse
import os


def cmd_prepare(args):
    from app.experiment.runners.prepare import prepare

    result = prepare(
        base_dir=args.output_dir,
        datasets=args.datasets,
        test_count=args.test_count,
        warmup_ratio=args.warmup_ratio,
        seed=args.seed,
    )
    print(f"Prepare done. Run ID: {result['run_id']}")
    total_test = sum(d["test_count"] for d in result["datasets"].values())
    total_warmup = sum(d["warmup_count"] for d in result["datasets"].values())
    print(f"  Test cases: {total_test}, Warmup: {total_warmup}")
    return result


def cmd_run(args):
    from app.experiment.runners.execute import execute

    prepared_dir = os.path.join(args.base_dir, args.run_id)
    result = execute(prepared_dir=prepared_dir)
    total = sum(len(r.get("cases", [])) for r in result.get("methods", {}).values())
    print(f"Run done. {total} cases across {len(result.get('methods', {}))} methods.")
    return result


def cmd_judge(args):
    from app.experiment.runners.judge import judge

    prepared_dir = os.path.join(args.base_dir, args.run_id)
    report = judge(prepared_dir=prepared_dir)

    print("\n" + "=" * 80)
    print("JUDGE REPORT")
    print("=" * 80)
    for method, metrics in report.get("summary", {}).items():
        wt = metrics.get("avg_weighted_total", 0)
        lat = metrics.get("avg_latency_ms", 0)
        comp = metrics.get("task_completion_rate", 0)
        print(
            f"  {method:<12} weighted={wt:.2f}  latency={lat:.0f}ms  completion={comp:.1%}"
        )

    return report


def cmd_all(args):
    prep = cmd_prepare(args)
    exp_dir = os.path.join(args.output_dir, "exp")
    run_args = argparse.Namespace(run_id=prep["run_id"], base_dir=exp_dir)
    cmd_run(run_args)
    judge_args = argparse.Namespace(run_id=prep["run_id"], base_dir=exp_dir)
    cmd_judge(judge_args)


def main():
    parser = argparse.ArgumentParser(
        description="Experiment Pipeline: prepare -> run -> judge"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--datasets", nargs="+", default=["sgd_calendar", "scheduler"])
    p.add_argument("--test-count", type=int, default=50)
    p.add_argument("--warmup-ratio", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", default="data")

    p = sub.add_parser("run")
    p.add_argument("--run-id", required=True)
    p.add_argument("--base-dir", default="data/exp")

    p = sub.add_parser("judge")
    p.add_argument("--run-id", required=True)
    p.add_argument("--base-dir", default="data/exp")

    p = sub.add_parser("all")
    p.add_argument("--datasets", nargs="+", default=["sgd_calendar", "scheduler"])
    p.add_argument("--test-count", type=int, default=50)
    p.add_argument("--warmup-ratio", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", default="data")

    args = parser.parse_args()
    {"prepare": cmd_prepare, "run": cmd_run, "judge": cmd_judge, "all": cmd_all}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
