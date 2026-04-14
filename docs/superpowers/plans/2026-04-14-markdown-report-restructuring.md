# Markdown 报告结构重设计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重新设计 markdown_formatters.py 生成的报告结构，遵循"头内容 → 固定内容 → 实验结果 → 结果分析"的清晰顺序，实现数据唯一性。

**Architecture:** 保持现有函数结构，重构 `generate_markdown_report` 的组装逻辑，新增 `md_header`、`md_experiment_groups`、`md_metric_definitions`、`md_results_table`、`md_results_detail`、`md_analysis` 等函数。

**Tech Stack:** Python 3.14, ruff, ty

---

## 任务 1: 实现 `md_header` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_header` 函数**

在 `_format_reasoning_type` 函数之后添加：

```python
def md_header(
    timestamp_display: str,
    model_name: str,
    type_names: str,
) -> str:
    """生成报告头内容."""
    lines = [
        "# VehicleMemBench 基准测试报告\n",
        f"- 生成时间：{timestamp_display}",
        f"- 评估模型：{model_name}",
        f"- 记忆类型：{type_names}\n",
    ]
    return "\n".join(lines)
```

- [ ] **Step 2: 运行 ruff check**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
```

- [ ] **Step 3: 运行 ruff format**

```bash
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
```

- [ ] **Step 4: 运行 ty check**

```bash
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 2: 实现 `md_experiment_groups` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_experiment_groups` 函数**

```python
def md_experiment_groups() -> str:
    """生成实验组介绍."""
    lines = [
        "## 2. 实验组介绍\n",
        "| 实验组 | 记忆类型 | 描述 | 理论意义 |",
        "|---|---|---|---|",
        "| none | Raw History | 无历史信息，让模型直接预测 | 基线性能 |",
        "| gold | Gold Memory | 直接提供真实最新用户偏好 | 理论性能上界 |",
        "| key_value | Key-Value Store | 将偏好组织为结构化键值对 | 精确检索能力 |",
        "| memory_bank | MemoryBank | 基于遗忘曲线的分层记忆 | 遗忘曲线检索能力 |\n",
    ]
    return "\n".join(lines)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 3: 实现 `md_metric_definitions` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_metric_definitions` 函数**

```python
def md_metric_definitions() -> str:
    """生成指标定义."""
    lines = [
        "## 3. 指标含义\n",
        "| 指标 | 描述 |",
        "|---|------|",
        "| ESM (Exact Match Rate) | 最终车辆状态与真值完全匹配的比例 |",
        "| F1 Positive | 字段级 F1，评估是否修改了正确的字段（字段级） |",
        "| F1 Change | 值级 F1，评估修改后的值是否正确（值级） |",
        "| F1 Negative | 负类 F1，评估是否避免了不应修改的字段被错误修改 |",
        "| Memory Score | 相对于 GOLD 理论上限的 ESM 比值 |",
        "| Δ% (vs Gold) | 与 GOLD 的 ESM 差距百分比 |",
        "| Avg Calls | 平均预测工具调用数 |",
        "| Avg Tokens | 平均输出 token 数 |",
        "| 失败数 | 执行失败的查询数量 |\n",
    ]
    return "\n".join(lines)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 4: 实现 `md_results_table` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_results_table` 函数**

```python
def md_results_table(report_data: dict[BenchMemoryMode, dict[str, Any]]) -> str:
    """生成实验结果总表（横向对比）."""
    lines = ["## 4. 实验结果\n"]
    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    has_gold = BenchMemoryMode.GOLD in report_data
    gold_esm = _num(report_data.get(BenchMemoryMode.GOLD, {}).get("exact_match_rate"))

    if not has_gold:
        lines.append("注意：未包含 GOLD 类型数据，Memory Score 和 Δ% 列不可用。\n")

    header = "| 记忆类型 | ESM | F1 Positive | F1 Change | Memory Score | Δ% (vs Gold) | Avg Calls | Avg Tokens | 失败数 |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)

    for mtype, metric in report_data.items():
        if metric.get("build_error"):
            lines.append(
                f"| {mtype.value} | 指标构建失败 | - | - | - | - | - | - | - |"
            )
            continue
        esm = _num(metric.get("exact_match_rate"))
        f1_pos = _num(metric.get("state_f1_positive"))
        f1_chg = _num(metric.get("state_f1_change"))
        ms = f"{_num(metric['memory_score']):.2%}" if "memory_score" in metric else "-"
        calls = _num(metric.get("avg_pred_calls"))
        tokens = _num(metric.get("avg_output_token"))
        failed = _num(metric.get("total_failed"))
        if has_gold and mtype != BenchMemoryMode.GOLD and gold_esm > 0:
            delta = (esm - gold_esm) / gold_esm
            delta_str = f"{delta:.2%}"
        else:
            delta_str = "-"
        lines.append(
            f"| {mtype.value} | {esm:.2%} | {f1_pos:.4f} | {f1_chg:.4f} | {ms} | {delta_str} | {calls:.1f} | {tokens:.1f} | {failed} |"
        )
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 5: 实现 `md_results_detail` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_results_detail` 函数**

```python
def md_results_detail(
    report_data: dict[BenchMemoryMode, dict[str, Any]],
) -> str:
    """生成各记忆类型详细指标."""
    lines = ["### 4.1 详细指标\n"]
    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    for mtype, metric in report_data.items():
        lines.append(f"#### {mtype.value}\n")
        if metric.get("build_error"):
            lines.append(
                "**指标构建失败**：该记忆类型的评估结果无法正常聚合，请检查原始数据。\n"
            )
            continue

        esm = _num(metric.get("exact_match_rate"))
        f1_pos = _num(metric.get("state_f1_positive"))
        f1_chg = _num(metric.get("state_f1_change"))
        f1_neg = _num(metric.get("state_f1_negative"))
        chg_acc = _num(metric.get("change_accuracy"))
        calls = _num(metric.get("avg_pred_calls"))
        tokens = _num(metric.get("avg_output_token"))
        failed = _num(metric.get("total_failed"))

        lines.append("| 指标 | 值 |")
        lines.append("|---|--- |")
        lines.append(f"| Exact Match Rate (ESM) | {esm:.2%} |")
        lines.append(f"| F1 Positive | {f1_pos:.4f} |")
        lines.append(f"| F1 Change | {f1_chg:.4f} |")
        lines.append(f"| F1 Negative | {f1_neg:.4f} |")
        lines.append(f"| Change Accuracy | {chg_acc:.4f} |")
        lines.append(f"| Avg Pred Calls | {calls:.1f} |")
        lines.append(f"| Avg Output Token | {tokens:.1f} |")
        lines.append(f"| 失败查询数 | {failed} |")
        if "memory_score" in metric:
            lines.append(f"| Memory Score | {_num(metric['memory_score']):.2%} |")
        lines.append("")

        by_rt = metric.get("by_reasoning_type", {})
        if by_rt:
            lines.append("**按推理类型细分：**\n")
            lines.append(
                "| 推理类型 | 样本数 | ESM | F1 Positive | F1 Change | Avg Calls |"
            )
            lines.append("|---|---|---|---|---|---|")
            for rt, raw_rt_metric in by_rt.items():
                rt_metric = raw_rt_metric or {}
                label = _format_reasoning_type(rt)
                rt_count = _num(rt_metric.get("count"))
                rt_esm = _num(rt_metric.get("exact_match_rate"))
                rt_f1p = _num(rt_metric.get("state_f1_positive"))
                rt_f1c = _num(rt_metric.get("state_f1_change"))
                rt_calls = _num(rt_metric.get("avg_pred_calls"))
                lines.append(
                    f"| {label} | {rt_count} | {rt_esm:.2%} | {rt_f1p:.4f} | {rt_f1c:.4f} | {rt_calls:.1f} |"
                )
            lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 6: 实现 `md_analysis` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 添加 `md_analysis` 函数**

该函数整合原 `md_reasoning_cross_comparison`、`md_query_analysis`、`md_summary` 的逻辑为"结果分析"章节。

```python
def md_analysis(
    report_data: dict[BenchMemoryMode, dict[str, Any]],
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> str:
    """生成结果分析章节."""
    lines = ["## 5. 结果分析\n"]

    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    lines.append(md_analysis_overview(report_data))
    lines.append(md_analysis_cross_reasoning(report_data))
    lines.append(md_analysis_query_cases(all_results))

    return "\n".join(lines)


def md_analysis_overview(report_data: dict[BenchMemoryMode, dict[str, Any]]) -> str:
    """生成各记忆类型表现分析."""
    lines: list[str] = ["### 5.1 各记忆类型表现分析\n"]

    total_tasks = sum(
        int(_num(m.get("completed_tasks"))) + int(_num(m.get("total_failed")))
        for m in report_data.values()
    )
    n_types = len(report_data)

    sorted_types = sorted(
        report_data.items(),
        key=lambda x: (
            -1 if x[1].get("build_error") else _num(x[1].get("exact_match_rate"))
        ),
        reverse=True,
    )

    lines.append(
        f"本次评估共测试了 {n_types} 种记忆类型，"
        f"共完成 {total_tasks} 条查询评估。"
        f"按完全匹配率（ESM）排名：\n"
    )
    for rank, (mtype, metric) in enumerate(sorted_types, 1):
        if metric.get("build_error"):
            lines.append(f"{rank}. {mtype.value}（指标构建失败）")
        else:
            esm = _num(metric.get("exact_match_rate"))
            lines.append(f"{rank}. {mtype.value}（ESM={esm:.2%}）")
    lines.append("")

    gold_metric = report_data.get(BenchMemoryMode.GOLD)
    if gold_metric:
        gold_esm = _num(gold_metric.get("exact_match_rate"))
        non_gold = [(mt, m) for mt, m in sorted_types if mt != BenchMemoryMode.GOLD]
        if non_gold:
            best_mt, best_metric = non_gold[0]
            ms = (
                _num(best_metric.get("memory_score"))
                if "memory_score" in best_metric
                else 0
            )
            lines.append(
                f"GOLD 类型作为理论上限达到 {gold_esm:.2%}，"
                f"最优非 GOLD 类型 {best_mt.value} "
                f"达到其 {ms:.2%} 的水平。\n"
            )

    return "\n".join(lines)


def md_analysis_cross_reasoning(
    report_data: dict[BenchMemoryMode, dict[str, Any]],
) -> str:
    """生成按推理类型交叉对比分析."""
    lines: list[str] = ["### 5.2 按推理类型交叉对比\n"]

    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    all_reasoning_types: set[str] = set()
    for metric in report_data.values():
        all_reasoning_types.update((metric.get("by_reasoning_type") or {}).keys())
    sorted_rt = sorted(all_reasoning_types)

    mtypes = sorted(report_data.keys())
    header = "| 推理类型 | " + " | ".join(mt.value for mt in mtypes) + " |"
    sep = "|---|" + "|".join("---" for _ in mtypes) + "|"
    lines.append(header)
    lines.append(sep)

    rt_best: dict[str, tuple[BenchMemoryMode, float]] = {}
    for rt in sorted_rt:
        label = _format_reasoning_type(rt)
        values: list[tuple[float, BenchMemoryMode]] = []
        for mt in mtypes:
            rt_data = (report_data[mt].get("by_reasoning_type") or {}).get(rt) or {}
            esm = _num(rt_data.get("exact_match_rate"))
            values.append((esm, mt))
        max_esm = max(v for v, _ in values) if values else 0
        best_mt = next(
            (mt for esm, mt in values if esm == max_esm and max_esm > 0), None
        )
        if best_mt is not None:
            rt_best[rt] = (best_mt, max_esm)
        cells: list[str] = []
        for esm, _mt in values:
            cell = f"{esm:.2%}"
            if esm == max_esm and max_esm > 0:
                cell = f"**{cell}**"
            cells.append(cell)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    if rt_best:
        parts: list[str] = []
        for rt, (best_mt, best_esm) in sorted(rt_best.items()):
            label = _format_reasoning_type(rt)
            parts.append(f"{label}上，{best_mt.value}（{best_esm:.2%}）表现最佳")
        lines.append("；".join(parts) + "。")
    lines.append("")

    return "\n".join(lines)


def md_analysis_query_cases(
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> str:
    """生成问题案例分析."""
    lines: list[str] = ["### 5.3 问题案例分析\n"]

    if not all_results:
        lines.append("无查询数据。\n")
        return "\n".join(lines)

    def _query_sort_key(q: dict[str, Any]) -> tuple[str, int, int]:
        return (
            str(q.get("memory_type", "")),
            int(_num(q.get("source_file", 0))),
            int(_num(q.get("task_id", 0))),
        )

    for mtype, queries in all_results.items():
        if not queries:
            continue
        lines.append(f"#### {mtype.value}\n")

        successes = [q for q in queries if q.get("exact_match")]
        successes.sort(key=_query_sort_key)
        if successes:
            lines.append("**完全匹配案例（前3条）：**\n")
            for q in successes[:3]:
                lines.extend(_format_query_entry(q, ["  - 完全匹配: ✅"]))

        non_match = [q for q in queries if not q.get("exact_match")]
        fp_candidates = [
            q
            for q in non_match
            if _num((q.get("state_score") or {}).get("FP")) > 0
        ]
        fp_sorted = sorted(
            fp_candidates,
            key=lambda q: (
                -_num((q.get("state_score") or {}).get("FP")),
                *_query_sort_key(q),
            ),
        )
        if fp_sorted:
            lines.append("**过度修改案例（FP 最高，前3条）：**\n")
            for q in fp_sorted[:3]:
                state_score = q.get("state_score") or {}
                fp = _num(state_score.get("FP"))
                diffs = state_score.get("differences") or []
                extra: list[str] = [f"  - FP={fp}"]
                extra.extend(f"  - 差异: {d}" for d in diffs)
                lines.extend(_format_query_entry(q, extra))

        fn_candidates = [
            q
            for q in non_match
            if _num((q.get("tool_score") or {}).get("fn")) > 0
        ]
        fn_sorted = sorted(
            fn_candidates,
            key=lambda q: (
                -_num((q.get("tool_score") or {}).get("fn")),
                *_query_sort_key(q),
            ),
        )
        if fn_sorted:
            lines.append("**遗漏调用案例（tool_score.fn 最高，前3条）：**\n")
            for q in fn_sorted[:3]:
                tool_score = q.get("tool_score") or {}
                fn = _num(tool_score.get("fn"))
                state_score = q.get("state_score") or {}
                diffs = state_score.get("differences") or []
                extra = [f"  - FN={fn}"]
                extra.extend(f"  - 差异: {d}" for d in diffs)
                lines.extend(_format_query_entry(q, extra))

    return "\n".join(lines)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 7: 重构 `generate_markdown_report` 函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 修改 `generate_markdown_report` 函数**

将现有的组装逻辑替换为新结构：

```python
def generate_markdown_report(
    output_dir: Path,
    report_data: dict[BenchMemoryMode, dict[str, Any]],
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> None:
    """生成 Markdown 格式基准测试报告."""
    now = datetime.now(tz=UTC)
    timestamp_display = now.strftime("%Y-%m-%d %H:%M:%S")
    first_metric = next(iter(report_data.values()), None)
    model_name = first_metric.get("model", "unknown") if first_metric else "unknown"
    type_names = ", ".join(mt.value for mt in report_data) if report_data else "无"

    parts: list[str] = [
        md_header(timestamp_display, model_name, type_names),
        md_experiment_groups(),
        md_metric_definitions(),
        md_results_table(report_data),
        md_results_detail(report_data),
        md_analysis(report_data, all_results),
    ]

    content = "\n".join(parts)
    filename = f"report-{now.strftime('%Y%m%d-%H%M%S-%f')}.md"
    out_path = output_dir / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Markdown 报告已写入: %s", out_path)
```

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 8: 删除旧函数

**Files:**
- Modify: `benchmark/VehicleMemBench/markdown_formatters.py`

- [ ] **Step 1: 删除以下旧函数（已整合到新结构中）**

- `md_overview`
- `md_memory_type_detail`
- `md_reasoning_cross_comparison`
- `md_query_analysis`
- `md_summary`

- [ ] **Step 2-4: 运行 ruff check/format/ty**

```bash
uv run ruff check --fix benchmark/VehicleMemBench/markdown_formatters.py
uv run ruff format benchmark/VehicleMemBench/markdown_formatters.py
uv run ty check benchmark/VehicleMemBench/markdown_formatters.py
```

---

## 任务 9: 运行测试验证

- [ ] **Step 1: 运行 pytest**

```bash
uv run pytest
```

---

## 任务 10: 提交代码

- [ ] **Step 1: 提交变更**

```bash
git add benchmark/VehicleMemBench/markdown_formatters.py
git commit -m "refactor: restructure markdown report to follow 4-section format"
```
