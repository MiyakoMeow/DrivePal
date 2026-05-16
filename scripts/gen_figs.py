"""生成论文实验对比图表。

用法:
    uv run python scripts/gen_figs.py                             # 默认输出至 archive/定稿-20260516/
    uv run python scripts/gen_figs.py -o archive/初稿-20260511     # 自定义输出目录
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TypedDict

import matplotlib
import matplotlib.font_manager
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

matplotlib.use("Agg")

# 中文字体：Noto Sans CJK → WenQuanYi Zen Hei / 微软雅黑 → sans-serif 回退
_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Microsoft YaHei",
    "SimHei",
]
_available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
_font = next((f for f in _FONT_CANDIDATES if f in _available), "sans-serif")
plt.rcParams["font.sans-serif"] = [_font, "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ── 常量 ──────────────────────────────────────────
LABELS = ["无记忆", "标准答案", "递归摘要", "键值存储", "MemoryBank in DrivePal"]
COLORS = ["#bdbdbd", "#ffc107", "#66bb6a", "#42a5f5", "#ef5350"]
REASONING_TYPES = ["偏好冲突", "条件约束", "错误纠正", "共指消解", "状态迁移"]

# ── 实验数据 ──────────────────────────────────────
#
# 数据来源说明：
#   前 4 组（无记忆 / 标准答案 / 递归摘要 / 键值存储）来自 VehicleMemBench 原始实验
#   （20260429），使用 deepseek-v4-flash + enable_thinking + reasoning_effort=max，
#   max_workers=20。键值存储组 reflect_num=20，其余 reflect_num=10。
#
#   第 5 组（MemoryBank in DrivePal）来自 DrivePal 本系统评测 (20260516)，
#   使用 deepseek-v4-flash 无 thinking，max_workers=6，reflect_num=10，
#   对应 DrivePal 的 MemoryBank（FAISS + Ebbinghaus 遗忘曲线）。
#
#   两组实验共用 VehicleMemBench benchmark/qa_data 50 个场景、500 条评测任务。
#   模型同为 deepseek-v4-flash，但 thinking 与否影响推理特征。
#
# 各推理类型含义（n 为任务数）：
#   - 偏好冲突 (n=149) — 用户新偏好与历史记录矛盾
#   - 条件约束 (n=102) — 带条件（天气/时间/位置）的约束推理
#   - 错误纠正 (n=62)  — 用户纠正历史错误信息
#   - 共指消解 (n=97)  — 代词/省略语与历史实体消解
#   - 状态迁移 (n=90)  — 连续对话中状态变更
#
# 字段说明：
#   exact_match       — 总体精确匹配率 (%)，表4-2
#   em_by_type        — 各推理类型精确匹配率 (%)，表4-3，顺序同 REASONING_TYPES
#   value_f1_by_type  — 各推理类型值级 F1 (%)，表4-4
#   calls_by_type     — 各推理类型平均工具调用次数，表4-5

class _ExperimentGroup(TypedDict):
    exact_match: float
    em_by_type: list[float]
    value_f1_by_type: list[float]
    calls_by_type: list[float]


class _SafetyVariant(TypedDict):
    compliance: float
    score_mean: float
    score_dist: list[int]
    intercept_rate: float


class _ArchVariant(TypedDict):
    overall: float
    safety: float
    reasonableness: float
    latency_p50_ms: int


class _PersonStage(TypedDict):
    match_rate: float


EXPERIMENTS: dict[str, _ExperimentGroup] = {
    "无记忆": {
        "exact_match": 19.40,
        "em_by_type": [20.13, 17.65, 22.58, 19.59, 17.78],
        "value_f1_by_type": [47.17, 48.38, 51.97, 56.77, 48.74],
        "calls_by_type": [4.70, 4.82, 4.39, 5.99, 5.11],
        # VMB thinking baseline: 裸 LLM，无记忆注入
    },
    "标准答案": {
        "exact_match": 86.20,
        "em_by_type": [93.29, 75.49, 79.03, 89.69, 87.78],
        "value_f1_by_type": [96.40, 87.90, 86.88, 95.09, 93.59],
        "calls_by_type": [2.35, 2.47, 2.50, 2.60, 2.43],
        # VMB thinking gold: 注入完美记忆，上界
    },
    "递归摘要": {
        "exact_match": 59.80,
        "em_by_type": [66.44, 53.92, 69.35, 56.70, 52.22],
        "value_f1_by_type": [78.70, 74.95, 84.55, 75.28, 74.25],
        "calls_by_type": [3.36, 3.86, 2.87, 3.86, 3.89],
        # VMB thinking summary: LLM 逐日递归摘要注入 prompt
    },
    "键值存储": {
        "exact_match": 51.60,
        "em_by_type": [62.42, 47.06, 66.13, 40.21, 41.11],
        "value_f1_by_type": [79.34, 66.77, 79.57, 67.82, 65.45],
        "calls_by_type": [7.75, 9.54, 7.98, 10.36, 10.24],
        # VMB thinking key_value: LLM 自维护 KV 存储 + 搜索，reflect_num=20
    },
    "MemoryBank in DrivePal": {
        "exact_match": 64.00,
        "em_by_type": [67.11, 57.84, 58.06, 70.10, 63.33],
        "value_f1_by_type": [79.88, 72.72, 71.46, 84.61, 76.89],
        "calls_by_type": [4.60, 4.47, 4.44, 5.01, 5.18],
        # DrivePal no-thinking: FAISS + Ebbinghaus 遗忘曲线，指令驱动规则引擎
    },
}


def _save(fig, name: str, out_dir: Path) -> None:
    path = out_dir / name
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {path}")


def _setup_ax(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _grouped_bars(ax, data_key: str, x_labels: list[str]) -> None:
    """通用分组柱状图：从 EXPERIMENTS[策略][data_key] 提取各推理类型的值。"""
    n_groups = len(x_labels)
    n_bars = len(LABELS)
    w = 0.8 / n_bars
    x = range(n_groups)
    for i, (label, color) in enumerate(zip(LABELS, COLORS, strict=True)):
        vals = EXPERIMENTS[label][data_key]
        offset = (i - (n_bars - 1) / 2) * w
        ax.bar([xi + offset for xi in x], vals, w, label=label, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=11)
    ax.legend(fontsize=9, ncol=3)


# ── 图4-1: 总体精确匹配率 ─────────────────────────
def fig_overall_match(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    values = [EXPERIMENTS[label]["exact_match"] for label in LABELS]
    bars = ax.bar(LABELS, values, color=COLORS, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.set_ylabel("精确匹配率 (%)", fontsize=12)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    _setup_ax(ax)
    _save(fig, "fig4-1_exact_match_overall.png", out_dir)


# ── 图4-2: 各推理类型精确匹配率 ───────────────────
def fig_reasoning_em(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, "em_by_type", REASONING_TYPES)
    ax.set_ylabel("精确匹配率 (%)", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-2_exact_match_by_type.png", out_dir)


# ── 图4-3: 各推理类型值级F1 ───────────────────────
def fig_reasoning_value_f1(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, "value_f1_by_type", REASONING_TYPES)
    ax.set_ylabel("值级F1 (%)", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-3_value_f1_by_type.png", out_dir)


# ── 图4-4: 各推理类型工具调用数 ───────────────────
def fig_reasoning_calls(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, "calls_by_type", REASONING_TYPES)
    ax.set_ylabel("平均工具调用次数", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-4_tool_calls_by_type.png", out_dir)


# ── 消融实验数据 (§4.7) ──────────────────────────
#
# 安全性消融：比较规则引擎各组件移除的效果
#   变体说明：
#     Full     — 完整系统（规则引擎 + 概率推断）
#     NO_PROB  — 移除概率推断（仅规则引擎）
#     NO_RULES — 移除规则引擎（仅概率推断）
SAFETY: dict[str, _SafetyVariant] = {
    "Full": {
        "compliance": 0.66,
        "score_mean": 3.76,
        "score_dist": [0, 22, 18, 22, 38],
        "intercept_rate": 0.68,
    },
    "NO_PROB": {
        "compliance": 0.62,
        "score_mean": 3.54,
        "score_dist": [4, 24, 18, 22, 32],
        "intercept_rate": 0.70,
    },
    "NO_RULES": {
        "compliance": 0.58,
        "score_mean": 3.52,
        "score_dist": [0, 34, 18, 10, 38],
        "intercept_rate": 0.0,
    },
}

# 架构消融：四智能体流水线 vs 单 LLM 直出
#   SingleLLM — 单次 LLM 调用完成全部决策
#   Full      — 四智能体流水线（分析→规划→执行→反思）
ARCH: dict[str, _ArchVariant] = {
    "SingleLLM": {
        "overall": 4.88,
        "safety": 5.0,
        "reasonableness": 4.9,
        "latency_p50_ms": 11486,
    },
    "Full": {
        "overall": 2.90,
        "safety": 2.86,
        "reasonableness": 3.0,
        "latency_p50_ms": 12052,
    },
}
ARCH_COHENS_D = 2.58
ARCH_P_VALUE = "2.1e-9"

# 个性化消融：反馈机制对偏好收敛的影响
#   三个阶段均为 FULL 变体下的不同操作：
#     高频提醒 — FULL 主动推送偏好确认
#     静默     — FULL 不推送，仅被动记录
#     视觉详情 — FULL 提供可视化偏好总结
#   附加聚合指标描述收敛特性
PERSON: dict[str, _PersonStage] = {
    "高频提醒": {"match_rate": 0.375},
    "静默": {"match_rate": 0.125},
    "视觉详情": {"match_rate": 0.50},
}
PERSON_CONVERGENCE = 0.8125  # 权重收敛速度（0=即时，1=未收敛）
PERSON_STABILITY = 0.0163  # 收敛稳定性（偏好切换后权重标准差）
PERSON_DIVERGENCE = 0.25  # 决策分歧度（混合阶段 FULL vs NO_FEEDBACK 差异）


def fig_ablation_safety(out_dir: Path) -> None:
    """图4-5: 安全性消融——合规率与评分分布."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    variants = list(SAFETY.keys())
    comp_vals = [SAFETY[v]["compliance"] * 100 for v in variants]
    colors_s = ["#ef5350", "#42a5f5", "#66bb6a"]
    bars = ax1.bar(
        variants, comp_vals, color=colors_s, edgecolor="white", linewidth=0.5
    )
    for bar, val in zip(bars, comp_vals, strict=True):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax1.set_ylabel("安全合规率 (%)", fontsize=12)
    ax1.set_ylim(0, 80)
    ax1.set_title("安全合规率 (safety_score≥4)", fontsize=12)
    _setup_ax(ax1)

    scores = [1, 2, 3, 4, 5]
    palette = ["#d32f2f", "#f44336", "#ffc107", "#66bb6a", "#1b5e20"]
    bottom = [0.0] * 3
    for i, score in enumerate(scores):
        vals = [SAFETY[v]["score_dist"][i] / 100 for v in variants]
        ax2.bar(
            variants,
            vals,
            bottom=bottom,
            color=palette[i],
            label=f"{score}分",
            edgecolor="white",
            linewidth=0.5,
        )
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
    ax2.set_ylabel("评分分布比例", fontsize=12)
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax2.set_title("Overall 评分分布", fontsize=12)
    ax2.legend(fontsize=8, ncol=5, loc="upper right")
    _setup_ax(ax2)

    # 拦截率标注
    ax2_twin = ax2.twiny()
    ax2_twin.set_xlim(ax2.get_xlim())
    ax2_twin.set_xticks(range(3))
    intercept_labels = [
        f"拦截率\n{SAFETY[v]['intercept_rate']:.0%}"
        for v in variants
    ]
    ax2_twin.set_xticklabels(intercept_labels, fontsize=9)
    ax2_twin.spines["top"].set_visible(False)

    _save(fig, "fig4-5_ablation_safety.png", out_dir)


def fig_ablation_architecture(out_dir: Path) -> None:
    """图4-6: 架构消融——决策质量与延迟对比."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    metrics = ["综合评分", "安全性", "合理性"]
    single_vals = [
        ARCH["SingleLLM"]["overall"],
        ARCH["SingleLLM"]["safety"],
        ARCH["SingleLLM"]["reasonableness"],
    ]
    full_vals = [
        ARCH["Full"]["overall"],
        ARCH["Full"]["safety"],
        ARCH["Full"]["reasonableness"],
    ]
    x = range(len(metrics))
    w = 0.3
    bars1 = ax1.bar(
        [xi - w / 2 for xi in x],
        single_vals,
        w,
        label="SingleLLM",
        color="#42a5f5",
        edgecolor="white",
    )
    bars2 = ax1.bar(
        [xi + w / 2 for xi in x],
        full_vals,
        w,
        label="Four-Agent",
        color="#ef5350",
        edgecolor="white",
    )
    for bar in bars1:
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.05,
            f"{bar.get_height():.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    for bar in bars2:
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.05,
            f"{bar.get_height():.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax1.set_xticks(x)
    ax1.set_xticklabels(metrics, fontsize=11)
    ax1.set_ylabel("评分 (1-5)", fontsize=12)
    ax1.set_ylim(0, 5.5)
    ax1.legend(fontsize=10)
    _setup_ax(ax1)
    ax1.text(
        0.5,
        0.95,
        f"Cohen's d={ARCH_COHENS_D}\np={ARCH_P_VALUE}",
        transform=ax1.transAxes,
        ha="center",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round", "fc": "#fff3e0"},
    )

    latency_labels = ["SingleLLM", "Four-Agent"]
    latency_vals = [
        ARCH["SingleLLM"]["latency_p50_ms"] / 1000,
        ARCH["Full"]["latency_p50_ms"] / 1000,
    ]
    bars = ax2.bar(
        latency_labels,
        latency_vals,
        color=["#42a5f5", "#ef5350"],
        edgecolor="white",
        linewidth=0.5,
    )
    for bar, val in zip(bars, latency_vals, strict=True):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            f"{val:.1f}s",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax2.set_ylabel("端到端延迟 P50 (秒)", fontsize=12)
    ax2.set_ylim(0, 15)
    ax2.set_title("执行效率（相近）", fontsize=12)
    _setup_ax(ax2)

    _save(fig, "fig4-6_ablation_architecture.png", out_dir)


def fig_ablation_personalization(out_dir: Path) -> None:
    """图4-7: 个性化消融——偏好匹配率与收敛."""
    fig, ax = plt.subplots(figsize=(9, 5.5))

    stages = list(PERSON.keys())
    match_rates = [PERSON[s]["match_rate"] * 100 for s in stages]

    bars = ax.bar(
        stages,
        match_rates,
        color=["#ffc107", "#42a5f5", "#66bb6a"],
        edgecolor="white",
        linewidth=0.5,
    )
    for bar, val in zip(bars, match_rates, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax.set_ylabel("偏好匹配率 (%)", fontsize=12)
    ax.set_ylim(0, 70)
    ax.set_title("FULL 变体各阶段偏好匹配率", fontsize=12)
    _setup_ax(ax)

    # 收敛指标标注
    info_text = (
        f"权重收敛速度: {PERSON_CONVERGENCE:.2f} (越小越快, 0=即时 1=未收敛)\n"
        f"收敛稳定性: σ={PERSON_STABILITY:.4f} (偏好切换后权重标准差)\n"
        f"决策分歧度: {PERSON_DIVERGENCE:.0%} (混合阶段FULL vs NO_FEEDBACK差异)"
    )
    ax.text(
        0.5,
        -0.35,
        info_text,
        transform=ax.transAxes,
        ha="center",
        fontsize=9,
        bbox={"boxstyle": "round", "fc": "#f5f5f5"},
    )

    _save(fig, "fig4-7_ablation_personalization.png", out_dir)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成论文实验对比图表")
    parser.add_argument(
        "--out-dir", "-o",
        type=Path,
        default=Path("archive/定稿-20260516"),
        help="输出目录 (default: archive/定稿-20260516)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"使用字体: {_font}")
    print(f"输出目录: {out_dir}")
    print("生成图表...")
    fig_overall_match(out_dir)
    fig_reasoning_em(out_dir)
    fig_reasoning_value_f1(out_dir)
    fig_reasoning_calls(out_dir)
    fig_ablation_safety(out_dir)
    fig_ablation_architecture(out_dir)
    fig_ablation_personalization(out_dir)
    print("完成。")


if __name__ == "__main__":
    main()
