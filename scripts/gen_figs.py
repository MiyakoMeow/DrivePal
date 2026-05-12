"""生成论文实验对比图表 → archive/figs/*.png

用法: uv run python scripts/gen_figs.py
"""

from __future__ import annotations

from pathlib import Path

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

OUT = Path("archive/figs")
OUT.mkdir(parents=True, exist_ok=True)

# ── 常量 ──────────────────────────────────────────
LABELS = ["无记忆", "标准答案", "递归摘要", "键值存储", "MemoryBank"]
COLORS = ["#bdbdbd", "#ffc107", "#66bb6a", "#42a5f5", "#ef5350"]
REASONING_TYPES = ["偏好冲突", "条件约束", "错误纠正", "共指消解", "状态迁移"]

# 表4-2: 总体
EXACT_MATCH = [19.40, 86.20, 59.80, 51.60, 62.00]

# 表4-3: 各推理类型精确匹配率 [类型][策略]
EM_MATRIX = [
    [20.13, 93.29, 66.44, 62.42, 61.74],
    [17.65, 75.49, 53.92, 47.06, 53.92],
    [22.58, 79.03, 69.35, 66.13, 64.52],
    [19.59, 89.69, 56.70, 40.21, 67.01],
    [17.78, 87.78, 52.22, 41.11, 64.44],
]

# 表4-4: 各推理类型值级F1 [类型][策略]
VALUE_F1_MATRIX = [
    [47.17, 96.40, 78.70, 79.34, 76.99],
    [48.38, 87.90, 74.95, 66.77, 74.72],
    [51.97, 86.88, 84.55, 79.57, 75.19],
    [56.77, 95.09, 75.28, 67.82, 79.41],
    [48.74, 93.59, 74.25, 65.45, 76.30],
]

# 表4-5: 工具调用数 [类型][策略]
CALLS_MATRIX = [
    [4.70, 2.35, 3.36, 7.75, 5.76],
    [4.82, 2.47, 3.86, 9.54, 6.19],
    [4.39, 2.50, 2.87, 7.98, 4.98],
    [5.99, 2.60, 3.86, 10.36, 5.62],
    [5.11, 2.43, 3.89, 10.24, 6.44],
]


def _save(fig, name: str) -> None:
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {path}")


def _setup_ax(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _grouped_bars(ax, matrix, x_labels) -> None:
    """通用分组柱状图：matrix[row][col] → col 为策略分组。"""
    n_groups = len(x_labels)
    n_bars = len(LABELS)
    w = 0.8 / n_bars
    x = range(n_groups)
    for i, (label, color) in enumerate(zip(LABELS, COLORS, strict=True)):
        vals = [matrix[j][i] for j in range(n_groups)]
        offset = (i - (n_bars - 1) / 2) * w
        ax.bar([xi + offset for xi in x], vals, w, label=label, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=11)
    ax.legend(fontsize=9, ncol=3)


# ── 图4-1: 总体精确匹配率 ─────────────────────────
def fig_overall_match() -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(LABELS, EXACT_MATCH, color=COLORS, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, EXACT_MATCH, strict=True):
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
    _save(fig, "fig4-1_exact_match_overall.png")


# ── 图4-2: 各推理类型精确匹配率 ───────────────────
def fig_reasoning_em() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, EM_MATRIX, REASONING_TYPES)
    ax.set_ylabel("精确匹配率 (%)", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-2_exact_match_by_type.png")


# ── 图4-3: 各推理类型值级F1 ───────────────────────
def fig_reasoning_value_f1() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, VALUE_F1_MATRIX, REASONING_TYPES)
    ax.set_ylabel("值级F1 (%)", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-3_value_f1_by_type.png")


# ── 图4-4: 各推理类型工具调用数 ───────────────────
def fig_reasoning_calls() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _grouped_bars(ax, CALLS_MATRIX, REASONING_TYPES)
    ax.set_ylabel("平均工具调用次数", fontsize=12)
    _setup_ax(ax)
    _save(fig, "fig4-4_tool_calls_by_type.png")


# ── 消融实验数据 (§4.7) ──────────────────────────
# 安全性组数据
SAFETY_COMPLIANCE = {"Full": 0.66, "NO_PROB": 0.62, "NO_RULES": 0.58}
SAFETY_SCORES = {"Full": 3.76, "NO_PROB": 3.54, "NO_RULES": 3.52}
SAFETY_DIST = {
    "Full": [0, 22, 18, 22, 38],
    "NO_RULES": [0, 34, 18, 10, 38],
    "NO_PROB": [4, 24, 18, 22, 32],
}
SAFETY_INTERCEPT = {"Full": 0.68, "NO_PROB": 0.70, "NO_RULES": 0.0}

# 架构组数据
ARCH_SCORES = {
    "overall": {"SingleLLM": 4.88, "Full": 2.90},
    "safety": {"SingleLLM": 5.0, "Full": 2.86},
    "reasonableness": {"SingleLLM": 4.9, "Full": 3.0},
}
ARCH_LATENCY_P50 = {"SingleLLM": 11486, "Full": 12052}
ARCH_COHENS_D = 2.58
ARCH_P_VALUE = "2.1e-9"

# 个性化组数据
PERSON_MATCHING = {"高频提醒": 0.375, "静默": 0.125, "视觉详情": 0.50}
PERSON_CONVERGENCE = 0.8125
PERSON_STABILITY = 0.0163
PERSON_DIVERGENCE = 0.25


def fig_ablation_safety() -> None:
    """图4-5: 安全性消融——合规率与评分分布."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    variants = list(SAFETY_COMPLIANCE.keys())
    comp_vals = [SAFETY_COMPLIANCE[v] * 100 for v in variants]
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
        vals = [SAFETY_DIST[v][i] / 100 for v in variants]
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
    intercept_labels = [f"拦截率\n{SAFETY_INTERCEPT[v]:.0%}" for v in variants]
    ax2_twin.set_xticklabels(intercept_labels, fontsize=9)
    ax2_twin.spines["top"].set_visible(False)

    _save(fig, "fig4-5_ablation_safety.png")


def fig_ablation_architecture() -> None:
    """图4-6: 架构消融——决策质量与延迟对比."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    metrics = ["综合评分", "安全性", "合理性"]
    single_vals = [
        ARCH_SCORES["overall"]["SingleLLM"],
        ARCH_SCORES["safety"]["SingleLLM"],
        ARCH_SCORES["reasonableness"]["SingleLLM"],
    ]
    full_vals = [
        ARCH_SCORES["overall"]["Full"],
        ARCH_SCORES["safety"]["Full"],
        ARCH_SCORES["reasonableness"]["Full"],
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
        ARCH_LATENCY_P50["SingleLLM"] / 1000,
        ARCH_LATENCY_P50["Full"] / 1000,
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

    _save(fig, "fig4-6_ablation_architecture.png")


def fig_ablation_personalization() -> None:
    """图4-7: 个性化消融——偏好匹配率与收敛."""
    fig, ax = plt.subplots(figsize=(9, 5.5))

    stages = list(PERSON_MATCHING.keys())
    match_rates = [PERSON_MATCHING[s] * 100 for s in stages]

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

    _save(fig, "fig4-7_ablation_personalization.png")


def main() -> None:
    print(f"使用字体: {_font}")
    print("生成图表...")
    fig_overall_match()
    fig_reasoning_em()
    fig_reasoning_value_f1()
    fig_reasoning_calls()
    fig_ablation_safety()
    fig_ablation_architecture()
    fig_ablation_personalization()
    print("完成。")


if __name__ == "__main__":
    main()
