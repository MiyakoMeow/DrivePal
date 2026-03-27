# Experiment Framework Fix Design

Date: 2026-03-28 (v2 — post-review revision)

## Problem Statement

The experiment framework for comparing 4 memory retrieval strategies (keyword, llm_only, embeddings, memorybank) has 6 issues preventing usable results:

1. **Missing entry script**: `run_exp.py` referenced in README does not exist
2. **Data pollution**: All methods share `data/events.json`, contaminating each other's runs
3. **Type mismatch**: `scenarios.json` types (`schedule_check/event_add/event_delete/general`) don't match `evaluation_config.json` types (`meeting/travel/shopping/contact`), causing `context_relatedness` to always be 0%
4. **Strategy Agent over-conservative**: 20/22 events have `content: "无提醒内容"`, starving evaluation keywords
5. **Crude scoring**: Character-level keyword overlap has poor discrimination
6. **No reproducibility**: Random test cases without seed control

## Solution: Minimal Fix (Plan A)

Fix the experiment framework, evaluation layer, and one minimal workflow change. Do NOT modify Agent prompts, Agent logic, or memory method implementations.

## Section 1: Entry Script & Data Isolation

### New file: `run_exp.py` (project root)

CLI entry point with arguments:
- `--methods`: list of methods to test (default: all 4)
- `--count`: test cases per method (default: 20)
- `--seed`: random seed (default: 42)

### Data isolation per method

For each method run:
1. Create temp directory: `data/exp_tmp/{method}/`
2. Initialize with blank data files: `events.json`, `interactions.json`, `memorybank_summaries.json`, `strategies.json`, `preferences.json`, `feedback.json`, `contexts.json`
3. Create `AgentWorkflow` with this temp `data_dir`
4. Run all test cases
5. Clean up temp directory after run

Note: `evaluation_config.json` is read from `config_dir` (not `data_dir`) by the runner, so it does NOT need to be copied to the temp dir.

### Runner modification

`ExperimentRunner._run_method()` accepts an explicit `data_dir` parameter instead of always using `self.data_dir`. This `data_dir` is also passed to `_get_latest_output()` so it reads events from the correct isolated directory.

## Section 2: Workflow Minimal Change — Preserve Raw LLM Output

### 2a. Always store raw LLM output in decision

In `workflow.py` `_strategy_node()`, after `json.loads(result)` succeeds, add `decision["raw"] = result` before the node returns. Currently `raw` is only set when JSON parsing fails. This one-line change ensures the full Strategy Agent output (including reasoning) is available for evaluation.

Also apply the same pattern in `_context_node()` and `_task_node()` for consistency, storing raw LLM output as `context["raw"]` and `task["raw"]`.

## Section 3: Evaluation Metrics Fix

### 3a. Type matching (fix P3)

Update `config/evaluation_config.json` to add `task_concepts` for all scenario types:

```json
{
  "task_concepts": {
    "schedule_check": ["时间", "日程", "安排", "会议", "查询", "提醒"],
    "event_add": ["添加", "创建", "提醒", "设置", "安排", "记录", "新建"],
    "event_delete": ["取消", "删除", "移除", "去掉", "不要"],
    "general": [],
    "meeting": ["时间", "提醒", "会议", "地点", "确认", "安排", "规划"],
    "travel": ["时间", "提醒", "行程", "地址", "确认", "安排", "规划", "出差"],
    "shopping": ["时间", "提醒", "购物", "确认", "安排", "规划", "买"],
    "contact": ["时间", "提醒", "联系", "确认", "安排", "规划"]
  }
}
```

Note: `general` type will always have 0% relatedness (no task concepts to match). This is expected behavior — general queries like "你好" have no task-relevant concepts.

### 3b. Rich output extraction (fix P4)

Change the source of `actual_output` for evaluation scoring in `runner.py`:

After `workflow.run()`, instead of reading from `_get_latest_output()` (which returns `decision.content` → "无提醒内容"), extract the full text for scoring:

Priority order:
1. `decision["raw"]` — full LLM response string (now always preserved per Section 2)
2. `decision.get("reasoning", "") + " " + decision.get("content", "")` — if raw unavailable
3. `result` — fallback

This captures the Strategy Agent's reasoning text which contains task-type analysis, event references, and domain concepts even when `should_remind=false`.

### 3c. Keyword overlap optimization (fix P5)

Change `split_words()` in `_evaluate_semantic_accuracy()`:

Use a **sliding-window bigram** approach for Chinese text. Instead of extracting consecutive runs (which returns whole sentences), generate all 2-character windows:

```python
def split_words(text: str) -> set:
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text.lower())
    english_words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    chinese_bigrams = {text[i:i+2] for i in range(len(chinese_chars) - 1)}
    return chinese_bigrams | english_words
```

This produces granular units like {"用户", "户正", "正在", "在开", "开车"} — noisy but gives fine-grained overlap scoring.

Adjust scoring formula:
- Each matched word contributes `0.05` (up to `0.4` cap at 8 matches)

## Section 4: Reproducibility & Reporting

### 4a. Random seed

`TestDataGenerator.generate_test_cases()` accepts optional `seed: int` parameter. When provided, calls `random.seed(seed)` before generation.

### 4b. Enhanced experiment results

`run_comparison()` output adds:
- `seed`: the seed used
- `per_case_results`: per-method, per-case detail (input, output, latency, accuracy, relatedness)

All methods run on the **same** test cases for fair comparison.

### 4c. Enhanced report

`generate_report()` outputs Markdown with:
- Summary table comparing all 4 methods across 4 metrics
- Per-case breakdown section

## Files to Modify

| File | Change |
|------|--------|
| `run_exp.py` (new) | CLI entry point |
| `app/agents/workflow.py` | Preserve raw LLM output in strategy/context/task nodes |
| `app/experiment/runner.py` | data_dir param, output extraction from raw, split_words bigram fix, per_case results |
| `app/experiment/test_data.py` | seed parameter |
| `config/evaluation_config.json` | add scenario type task_concepts |

## Out of Scope

- Strategy Agent prompt changes
- Memory method implementation changes
- LLM-as-Judge evaluation
- Dead code cleanup (`_extract_task_indicators`, incomplete `type_patterns`)
