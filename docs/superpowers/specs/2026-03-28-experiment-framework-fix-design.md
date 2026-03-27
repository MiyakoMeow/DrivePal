# Experiment Framework Fix Design

Date: 2026-03-28

## Problem Statement

The experiment framework for comparing 4 memory retrieval strategies (keyword, llm_only, embeddings, memorybank) has 6 issues preventing usable results:

1. **Missing entry script**: `run_exp.py` referenced in README does not exist
2. **Data pollution**: All methods share `data/events.json`, contaminating each other's runs
3. **Type mismatch**: `scenarios.json` types (`schedule_check/event_add/event_delete/general`) don't match `evaluation_config.json` types (`meeting/travel/shopping/contact`), causing `context_relatedness` to always be 0%
4. **Strategy Agent over-conservative**: 20/22 events have `content: "无提醒内容"`, starving evaluation keywords
5. **Crude scoring**: Character-level keyword overlap has poor discrimination
6. **No reproducibility**: Random test cases without seed control

## Solution: Minimal Fix (Plan A)

Do NOT modify Agent logic. Only fix the experiment framework and evaluation layer.

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
3. Copy `config/evaluation_config.json` to temp dir (preserving eval config access)
4. Create `AgentWorkflow` with this temp `data_dir`
5. Run all test cases
6. Clean up temp directory after run

### Runner modification

`ExperimentRunner._run_method()` accepts an explicit `data_dir` parameter instead of always using `self.data_dir`.

## Section 2: Evaluation Metrics Fix

### 2a. Type matching (fix P3)

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

### 2b. Rich output extraction (fix P4)

Change the source of `actual_output` in `runner.py:256`:

Priority order:
1. `decision.raw` — the full JSON string from Strategy Agent (contains reasoning, remind_content, etc.)
2. `decision.reasoning` + `decision.content` — if JSON parse succeeds
3. `result` — fallback (current behavior: `"提醒已发送: {content}"`)

Implementation: In `_run_method`, after `workflow.run()`, read the latest event's `decision.raw` field. This captures the Strategy Agent's full analysis even when `should_remind=false`.

### 2c. Keyword overlap optimization (fix P5)

Change `split_words()` in `_evaluate_semantic_accuracy()`:

- Before: single Chinese characters via `[\u4e00-\u9fff]+` then joining into set of individual chars
- After: Chinese bigrams+ via `[\u4e00-\u9fff]{2,}` plus English words. This captures meaningful word units like "会议", "提醒", "安排" rather than individual chars.

Adjust scoring formula:
- Each matched word contributes `0.05` (up to `0.4` cap)
- This gives better discrimination: 1 word = 0.05, 8 words = 0.4

## Section 3: Reproducibility & Reporting

### 3a. Random seed

`TestDataGenerator.generate_test_cases()` accepts optional `seed: int` parameter. When provided, calls `random.seed(seed)` before generation.

### 3b. Enhanced experiment results

`run_comparison()` output adds:
- `seed`: the seed used
- `per_case_results`: per-method, per-case detail (input, output, latency, accuracy, relatedness)

All methods run on the **same** test cases for fair comparison.

### 3c. Enhanced report

`generate_report()` outputs Markdown with:
- Summary table comparing all 4 methods across 4 metrics
- Per-case breakdown section

## Files to Modify

| File | Change |
|------|--------|
| `run_exp.py` (new) | CLI entry point |
| `app/experiment/runner.py` | data_dir param, output extraction, split_words fix, per_case results |
| `app/experiment/test_data.py` | seed parameter |
| `config/evaluation_config.json` | add scenario type task_concepts |

## Out of Scope

- Strategy Agent prompt changes
- Agent workflow logic changes
- Memory method implementation changes
- LLM-as-Judge evaluation
