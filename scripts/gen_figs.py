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
    "Noto Sans CJK SC", "Noto Sans CJK JP", "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei", "Microsoft YaHei", "SimHei",
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
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=10)
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


def main() -> None:
    print(f"使用字体: {_font}")
    print("生成图表...")
    fig_overall_match()
    fig_reasoning_em()
    fig_reasoning_value_f1()
    fig_reasoning_calls()
    print("完成。")


if __name__ == "__main__":
    main()
