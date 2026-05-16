"""DrivePal × VehicleMemBench 评估入口.

子命令（无子命令时默认等价于 run）:
    run         — 默认 drivepal 组，--all 全量 5 组
    model       — 单组模型评测（none/gold/summary/key_value）
    memory-add  — 写入历史至 DrivePal MemoryBank
    memory-test — 使用 DrivePal MemoryBank 评测

run 结果存储至 data/vehicle_mem_bench/ 下，命名与原项目一致:
    data/vehicle_mem_bench/drivepal_model_eval_{ none|gold|summary|key_value }_{model}_{timestamp}/
    data/vehicle_mem_bench/drivepal_memory_eval_drivepal_{model}_{timestamp}/

每目录内含 metric.json + report.txt + results.json（或 all_results.json）。

VehicleMemBench 代码来源（默认与 DrivePal 同级目录）:
    --vmb-root <path>  指定路径
    VMB_ROOT 环境变量   指定路径

模型参数（--api-base / --api-key / --model）可选，不传时从 DrivePal
config/llm.toml 读取。可用 --model-group 切换模型组（默认 "default"）。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── VehicleMemBench 路径 ──


def _resolve_vmb_root(args: argparse.Namespace) -> Path:
    """返回 VehicleMemBench 项目根。优先级: CLI > env > 同级目录。"""
    from_cli = getattr(args, "vmb_root", None)
    if from_cli:
        return Path(from_cli).resolve()
    from_env = os.environ.get("VMB_ROOT")
    if from_env:
        return Path(from_env).resolve()
    return Path(__file__).resolve().parent.parent.parent.parent / "VehicleMemBench"


def _ensure_vmb_on_path(vmb_root: Path) -> None:
    if str(vmb_root) not in sys.path:
        sys.path.insert(0, str(vmb_root))


def _sync_adapter_vmb_root(vmb_root: Path) -> None:
    """将 VMB 根同步至 adapter 模块。"""
    from experiments.vehicle_mem_bench.adapter import set_vmb_root

    set_vmb_root(str(vmb_root))


# ── 模型配置（来自 DrivePal config） ──


def _resolve_model_config(group_name: str = "default") -> dict[str, str]:
    """从 DrivePal config/llm.toml 按模型组名解析 API 配置.

    Args:
        group_name: model_groups 中的组名（如 "default", "vmb", "smart"）.

    Returns:
        {"api_base": ..., "api_key": ..., "model": ...}
        解析失败返回空 dict.

    """
    try:
        from app.models.settings import LLMSettings

        settings = LLMSettings.load()
        providers = settings.get_model_group_providers(group_name)
    except Exception as exc:
        logger.warning(
            "Failed to resolve model config for group %r: %s", group_name, exc
        )
        return {}
    if not providers:
        return {}
    p = providers[0]
    result: dict[str, str] = {
        "api_base": p.provider.base_url or "",
        "model": p.provider.model,
    }
    if p.provider.api_key:
        result["api_key"] = p.provider.api_key
    return result


def _resolve_api(args: argparse.Namespace) -> dict[str, str]:
    """合并 CLI 参数与 config 默认值，返回最终 API 配置."""
    group = getattr(args, "model_group", None) or "default"
    defaults = _resolve_model_config(group)
    return {
        "api_base": args.api_base or defaults.get("api_base", ""),
        "api_key": args.api_key
        or defaults.get("api_key", os.environ.get("OPENAI_API_KEY", "")),
        "model": args.model or defaults.get("model", ""),
    }


# ── CLI ──


def _add_vmb_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--vmb-root", type=str, default=None)


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DrivePal × VehicleMemBench 评估",
    )
    sub = parser.add_subparsers(dest="command")

    # ── model ──
    model_p = sub.add_parser(
        "model",
        help="模型评测（none/gold/summary/key_value）",
    )
    _add_vmb_arg(model_p)
    model_p.add_argument(
        "--memory-type",
        type=str,
        required=True,
        choices=["none", "gold", "summary", "key_value"],
        help="记忆策略: 无/黄金/递归摘要/键值存储",
    )
    model_p.add_argument("--benchmark-dir", type=str, default="")
    model_p.add_argument("--model-group", type=str, default=None)
    model_p.add_argument("--api-base", type=str, default=None)
    model_p.add_argument("--api-key", type=str, default=None)
    model_p.add_argument("--model", type=str, default=None)
    model_p.add_argument("--file-range", type=str, default=None)
    model_p.add_argument("--reflect-num", type=int, default=10)
    model_p.add_argument("--sample-size", type=int, default=None)
    model_p.add_argument("--output-dir", type=str, default=None)
    model_p.add_argument("--max-workers", type=int, default=6)
    model_p.add_argument("--prefix", type=str, default="drivepal_model_eval")

    # ── memory add ──
    mem_add_p = sub.add_parser(
        "memory-add",
        help="写入 history 至 DrivePal MemoryBank",
    )
    _add_vmb_arg(mem_add_p)
    mem_add_p.add_argument("--memory-url", type=str, default=None)
    mem_add_p.add_argument("--history-dir", type=str, required=True)
    mem_add_p.add_argument("--file-range", type=str, default=None)
    mem_add_p.add_argument("--max-workers", type=int, default=4)

    # ── memory test ──
    mem_test_p = sub.add_parser(
        "memory-test",
        help="使用 DrivePal MemoryBank 运行评测",
    )
    _add_vmb_arg(mem_test_p)
    mem_test_p.add_argument("--benchmark-dir", type=str, required=True)
    mem_test_p.add_argument("--memory-url", type=str, default=None)
    mem_test_p.add_argument("--model-group", type=str, default=None)
    mem_test_p.add_argument("--api-base", type=str, default=None)
    mem_test_p.add_argument("--api-key", type=str, default=None)
    mem_test_p.add_argument("--model", type=str, default=None)
    mem_test_p.add_argument("--file-range", type=str, default=None)
    mem_test_p.add_argument("--reflect-num", type=int, default=10)
    mem_test_p.add_argument("--max-workers", type=int, default=6)
    mem_test_p.add_argument("--sample-size", type=int, default=None)
    mem_test_p.add_argument("--output-dir", type=str, default=None)

    # ── run ──
    run_p = sub.add_parser(
        "run",
        help="默认仅跑 drivepal 组；--all 全量 5 组",
    )
    _add_vmb_arg(run_p)
    run_p.add_argument(
        "--all",
        action="store_true",
        help="全量运行 5 组（none+gold+summary+key_value+drivepal）",
    )
    run_p.add_argument("--output-dir", type=str, default=None)
    run_p.add_argument("--memory-url", type=str, default=None)
    run_p.add_argument("--model-group", type=str, default=None)
    run_p.add_argument("--api-base", type=str, default=None)
    run_p.add_argument("--api-key", type=str, default=None)
    run_p.add_argument("--model", type=str, default=None)
    run_p.add_argument("--file-range", type=str, default=None)
    run_p.add_argument("--reflect-num", type=int, default=10)
    run_p.add_argument("--max-workers", type=int, default=6)
    run_p.add_argument("--sample-size", type=int, default=None)
    run_p.add_argument("--benchmark-dir", type=str, default=None)

    return parser


# ── 命令处理 ──


def _cmd_model(args: argparse.Namespace) -> None:
    vmb_root = _resolve_vmb_root(args)
    _ensure_vmb_on_path(vmb_root)
    from evaluation.model_evaluation import model_evaluation

    api = _resolve_api(args)
    if not api["api_base"] or not api["model"]:
        msg = (
            "无法解析模型配置。请通过 --api-base / --api-key / --model 提供，"
            "或确保 config/llm.toml 配置正确。"
        )
        raise RuntimeError(msg)

    benchmark_dir = args.benchmark_dir or str(vmb_root / "benchmark" / "qa_data")

    model_evaluation(
        benchmark_dir=benchmark_dir,
        memory_type=args.memory_type,
        sample_size=args.sample_size,
        api_base=api["api_base"],
        api_key=api["api_key"],
        model=api["model"],
        reflect_num=args.reflect_num,
        prefix=args.prefix,
        file_range=args.file_range,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
    )


def _cmd_memory_add(args: argparse.Namespace) -> None:
    vmb_root = _resolve_vmb_root(args)
    _sync_adapter_vmb_root(vmb_root)
    from experiments.vehicle_mem_bench.adapter import run_add

    run_add(args)


def _cmd_memory_test(args: argparse.Namespace) -> None:
    vmb_root = _resolve_vmb_root(args)
    _ensure_vmb_on_path(vmb_root)

    from evaluation.memorysystems import SYSTEM_MODULES

    from experiments.vehicle_mem_bench import adapter as drivepal_adapter

    SYSTEM_MODULES["drivepal"] = drivepal_adapter

    from evaluation.memorysystem_evaluation import memorysystem_evaluation

    api = _resolve_api(args)
    if not api["api_base"] or not api["model"]:
        msg = (
            "无法解析模型配置。请通过 --api-base / --api-key / --model 提供，"
            "或确保 config/llm.toml 配置正确。"
        )
        raise RuntimeError(msg)

    memorysystem_evaluation(
        benchmark_dir=args.benchmark_dir,
        api_base=api["api_base"],
        api_key=api["api_key"],
        model=api["model"],
        memory_system="drivepal",
        reflect_num=args.reflect_num,
        file_range=args.file_range,
        prefix="drivepal_memory_eval",
        sample_size=args.sample_size,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
    )


# ── run ──


def _cmd_run(args: argparse.Namespace) -> None:
    """默认仅跑 drivepal 评测；--all 全量 5 组。"""
    vmb_root = _resolve_vmb_root(args)
    _ensure_vmb_on_path(vmb_root)

    api = _resolve_api(args)
    if not api["api_base"] or not api["model"]:
        msg = (
            "无法解析模型配置。请通过 --api-base / --api-key / --model 提供，"
            "或确保 config/llm.toml 配置正确。"
        )
        raise RuntimeError(msg)

    model_slug = api["model"].replace("/", "_")
    base_out = Path(
        args.output_dir
        or Path(__file__).resolve().parent.parent.parent / "data" / "vehicle_mem_bench"
    )
    base_out.mkdir(parents=True, exist_ok=True)

    benchmark_dir = args.benchmark_dir or str(vmb_root / "benchmark" / "qa_data")
    history_dir = str(vmb_root / "benchmark" / "history")

    reflect_num = args.reflect_num
    max_workers = args.max_workers
    file_range = args.file_range
    sample_size = args.sample_size

    # ── 1–4: 模型评测（仅 --all 时运行）──
    # 命名: {prefix}_{model}_{timestamp}/
    # 与原项目 (model_test.sh) 一致: 每 memory_type 独立 prefix
    if args.all:
        from evaluation.model_evaluation import model_evaluation

        for memory_type in ("none", "gold", "summary", "key_value"):
            prefix = f"drivepal_model_eval_{memory_type}"
            print(f"\n{'=' * 60}")
            print(f"[run] 模型评测: {memory_type}")
            print(f"[run] prefix={prefix}  →  {base_out}/{prefix}_{model_slug}_*/")
            print(f"{'=' * 60}\n")
            model_evaluation(
                benchmark_dir=benchmark_dir,
                memory_type=memory_type,
                sample_size=sample_size,
                api_base=api["api_base"],
                api_key=api["api_key"],
                model=api["model"],
                reflect_num=reflect_num,
                prefix=prefix,
                file_range=file_range,
                output_dir=str(base_out),
                max_workers=max_workers,
            )

    # ── 5: DrivePal MemoryBank 评测 ──
    # phase A: memory-add
    _sync_adapter_vmb_root(vmb_root)
    from experiments.vehicle_mem_bench.adapter import run_add

    add_args = argparse.Namespace(
        history_dir=history_dir,
        file_range=file_range,
        max_workers=max_workers,
        memory_url=args.memory_url,
    )
    print(f"\n{'=' * 60}")
    print("[run] DrivePal MemoryBank: 写入历史")
    print(f"{'=' * 60}\n")
    run_add(add_args)

    # phase B: memory-test
    # 命名: {prefix}_{memory_system}_{model}_{timestamp}/
    # 与原项目 (memorysystem_test.sh) 一致
    from evaluation.memorysystems import SYSTEM_MODULES

    from experiments.vehicle_mem_bench import adapter as drivepal_adapter

    SYSTEM_MODULES["drivepal"] = drivepal_adapter

    from evaluation.memorysystem_evaluation import memorysystem_evaluation

    mem_prefix = "drivepal_memory_eval"
    print(f"\n{'=' * 60}")
    print("[run] DrivePal MemoryBank: 评测")
    print(
        f"[run] prefix={mem_prefix}  →  {base_out}/{mem_prefix}_drivepal_{model_slug}_*/"
    )
    print(f"{'=' * 60}\n")
    memorysystem_evaluation(
        benchmark_dir=benchmark_dir,
        api_base=api["api_base"],
        api_key=api["api_key"],
        model=api["model"],
        memory_system="drivepal",
        reflect_num=reflect_num,
        file_range=file_range,
        prefix=mem_prefix,
        sample_size=sample_size,
        output_dir=str(base_out),
        max_workers=max_workers,
    )

    print(f"\n{'=' * 60}")
    print("[run] 全量运行完成")
    print(f"结果目录: {base_out}")
    print(f"{'=' * 60}\n")


# ── 入口 ──


def main() -> None:
    """CLI 入口。无子命令时默认跑 run。"""
    parser = _build_cli()
    args = parser.parse_args()

    dispatch: dict[str, Any] = {
        "model": _cmd_model,
        "memory-add": _cmd_memory_add,
        "memory-test": _cmd_memory_test,
        "run": _cmd_run,
    }
    handler = dispatch.get(args.command, _cmd_run)
    handler(args)


if __name__ == "__main__":
    main()
