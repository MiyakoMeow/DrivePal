import argparse
import shutil
from datetime import datetime
from pathlib import Path
from app.experiment.runner import ExperimentRunner
from app.experiment.test_data import TestDataGenerator
from app.storage.init_data import init_storage
from app.storage.json_store import JSONStore


def main():
    parser = argparse.ArgumentParser(description="运行记忆方式对比实验")
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["keyword", "llm_only", "embeddings", "memorybank"],
    )
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    valid_methods = {"keyword", "llm_only", "embeddings", "memorybank"}
    invalid = set(args.methods) - valid_methods
    if invalid:
        parser.error(f"Invalid methods: {invalid}")

    print(f"Generating {args.count} test cases (seed={args.seed})...")
    gen = TestDataGenerator()
    test_cases = gen.generate_test_cases(count=args.count, seed=args.seed)
    print(f"Test cases generated: {len(test_cases)}")

    runner = ExperimentRunner(data_dir="data", config_dir="config")

    combined_results = {
        "timestamp": datetime.now().isoformat(),
        "test_cases": len(test_cases),
        "methods": args.methods,
        "seed": args.seed,
        "metrics": {},
    }

    for method in args.methods:
        print(f"\n--- Running method: {method} ---")
        temp_dir = Path("data") / "exp_tmp" / method

        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        init_storage(str(temp_dir))

        (temp_dir / "experiment_results.json").unlink(missing_ok=True)

        method_results = runner._run_method(method, test_cases, data_dir=str(temp_dir))
        combined_results["metrics"][method] = method_results

        metrics = method_results
        print(f"  Latency: {metrics['avg_latency_ms']:.1f}ms")
        print(f"  Completion: {metrics['task_completion_rate'] * 100:.1f}%")
        print(f"  Semantic: {metrics.get('semantic_accuracy', 0) * 100:.1f}%")
        print(f"  Relatedness: {metrics.get('context_relatedness', 0) * 100:.1f}%")

        shutil.rmtree(temp_dir, ignore_errors=True)

    results_store = JSONStore("data", "experiment_results.json", list)
    results_store.append(combined_results)

    print("\n" + "=" * 50)
    print(runner.generate_report())


if __name__ == "__main__":
    main()
