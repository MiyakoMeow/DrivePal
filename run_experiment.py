#!/usr/bin/env python3
"""独立实验运行脚本，支持四种记忆检索方法的对比实验.

使用方法:
    python run_experiment.py                    # 运行完整实验
    python run_experiment.py --methods keyword llm_only  # 只运行指定方法
    python run_experiment.py --test-cases 4   # 指定测试用例数量（每种类型）

实验特点:
- 每个测试用例使用独立的 workflow 实例，避免状态污染
- embedding 模型使用缓存，避免重复加载
- 每个方法在独立的数据目录中运行
"""

import argparse
import json
import os
import shutil
import time
from datetime import datetime

from app.experiment.runner import ExperimentRunner


def setup_test_dir(test_data_dir: str) -> None:
    """初始化测试数据目录."""
    if os.path.exists(test_data_dir):
        shutil.rmtree(test_data_dir)
    os.makedirs(test_data_dir)

    for fname in [
        "events.json",
        "strategies.json",
        "interactions.json",
        "memorybank_summaries.json",
        "feedback.json",
    ]:
        with open(os.path.join(test_data_dir, fname), "w", encoding="utf-8") as f:
            if fname == "strategies.json":
                json.dump({}, f)
            elif fname in ["events.json", "interactions.json", "feedback.json"]:
                json.dump([], f)
            else:
                json.dump({"daily_summaries": {}, "overall_summary": ""}, f)


def get_test_cases(count_per_type: int = 2) -> list[dict]:
    """获取测试用例.

    Args:
        count_per_type: 每种类型生成的测试用例数量

    Returns:
        测试用例列表

    """
    scenarios = [
        {
            "type": "schedule_check",
            "templates": [
                "现在几点了？",
                "今天有什么安排？",
                "明天有什么日程？",
                "这周还剩什么？",
            ],
        },
        {
            "type": "event_add",
            "templates": [
                "提醒我下午三点开会",
                "明天早上九点有个电话",
                "记一下今天晚上买牛奶",
                "创建明天下午的会议",
            ],
        },
        {
            "type": "event_delete",
            "templates": [
                "取消明天的会议",
                "删除这个提醒",
                "不要提醒我了",
                "取消下午的约会",
            ],
        },
        {
            "type": "general",
            "templates": [
                "你好",
                "今天天气怎么样？",
                "最近怎么样？",
                "hello",
            ],
        },
    ]

    test_cases = []
    for scenario in scenarios:
        templates = scenario.get("templates", [])
        for i, template in enumerate(templates[:count_per_type]):
            test_cases.append({"input": template, "type": scenario["type"]})

    return test_cases


def run_full_experiment(
    methods: list[str] | None = None,
    test_cases: list[dict] | None = None,
    base_test_dir: str = "data/experiment",
    seed: int = 42,
) -> dict:
    """运行完整对比实验.

    Args:
        methods: 要测试的方法列表，默认为所有四种
        test_cases: 测试用例列表，默认为自动生成
        base_test_dir: 测试数据目录
        seed: 随机种子

    Returns:
        实验结果字典

    """
    if methods is None:
        methods = ["keyword", "llm_only", "embeddings", "memorybank"]

    if test_cases is None:
        test_cases = get_test_cases(count_per_type=2)

    all_results = {
        "timestamp": datetime.now().isoformat(),
        "test_cases_count": len(test_cases),
        "methods": methods,
        "seed": seed,
        "test_cases": [{"input": tc["input"], "type": tc["type"]} for tc in test_cases],
        "metrics": {},
    }

    print("=" * 80)
    print("MEMORY RETRIEVAL COMPARISON EXPERIMENT")
    print("=" * 80)
    print(f"\nTest cases: {len(test_cases)}")
    for tc in test_cases:
        print(f"  [{tc['type']}] {tc['input']}")

    print(f"\nMethods: {', '.join(methods)}")
    print(f"Random seed: {seed}")

    total_start_time = time.time()

    for method in methods:
        method_start_time = time.time()
        print(f"\n{'=' * 60}")
        print(f"Running: {method}")
        print(f"{'=' * 60}")

        test_data_dir = os.path.join(base_test_dir, method)
        setup_test_dir(test_data_dir)

        runner = ExperimentRunner(data_dir=test_data_dir, config_dir="config")

        try:
            results = runner.run_comparison(
                test_cases=test_cases,
                methods=[method],
                data_dir=test_data_dir,
                seed=seed,
            )
            method_metrics = results["metrics"][method]
            all_results["metrics"][method] = method_metrics

            method_elapsed = time.time() - method_start_time
            print(f"\n{method}:")
            print(f"  Total time: {method_elapsed:.1f}s")
            print(f"  Avg latency: {method_metrics['avg_latency_ms']:.1f}ms")
            print(f"  Task completion: {method_metrics['task_completion_rate']:.2f}")
            print(
                f"  Semantic accuracy: {method_metrics.get('semantic_accuracy', 0):.2f}"
            )
            print(
                f"  Context relatedness: {method_metrics.get('context_relatedness', 0):.2f}"
            )

            for case in method_metrics.get("per_case", []):
                output = case["output"]
                if len(output) > 100:
                    output = output[:100] + "..."
                print(f"\n  [{case['type']}] {case['input']}")
                print(f"    -> {output}")
                print(
                    f"    Sem: {case['semantic_accuracy']:.2f} | Ctx: {case['context_relatedness']:.2f}"
                )

        except Exception as e:
            print(f"\n{method}: FAILED - {e}")
            import traceback

            traceback.print_exc()

    total_elapsed = time.time() - total_start_time

    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"\nTotal time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f}min)")
    print(
        f"\n{'Method':<12} {'Avg Latency(ms)':<18} {'Completion':<12} {'Semantic Acc':<14} {'Context Rel':<14}"
    )
    print("-" * 80)
    for method in methods:
        if method in all_results["metrics"]:
            m = all_results["metrics"][method]
            print(
                f"{method:<12} {m['avg_latency_ms']:<18.1f} "
                f"{m['task_completion_rate']:<12.2f} "
                f"{m.get('semantic_accuracy', 0):<14.2f} "
                f"{m.get('context_relatedness', 0):<14.2f}"
            )
        else:
            print(f"{method:<12} {'FAILED':<18}")

    results_file = os.path.join(base_test_dir, "experiment_results.json")
    os.makedirs(os.path.dirname(results_file), exist_ok=True)
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {results_file}")

    return all_results


def main():
    """命令行入口点."""
    parser = argparse.ArgumentParser(
        description="Run memory retrieval comparison experiment"
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=["keyword", "llm_only", "embeddings", "memorybank"],
        help="Methods to test (default: all four)",
    )
    parser.add_argument(
        "--test-cases",
        type=int,
        default=2,
        help="Number of test cases per type (default: 2)",
    )
    parser.add_argument(
        "--test-dir",
        default="data/experiment",
        help="Base test data directory (default: data/experiment)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )

    args = parser.parse_args()

    test_cases = get_test_cases(count_per_type=args.test_cases)
    run_full_experiment(
        methods=args.methods,
        test_cases=test_cases,
        base_test_dir=args.test_dir,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
