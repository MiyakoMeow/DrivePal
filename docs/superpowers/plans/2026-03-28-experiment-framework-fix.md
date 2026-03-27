# Experiment Framework Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the experiment framework to produce usable comparison results for 4 memory methods, with data isolation, corrected evaluation metrics, and reproducibility.

**Architecture:** CLI entry script creates isolated temp data directories per method, runs the same test cases through each method's workflow, and scores outputs using fixed evaluation metrics. The workflow gets a minimal one-line change to preserve raw LLM output.

**Tech Stack:** Python 3.13, LangGraph, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-28-experiment-framework-fix-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `run_exp.py` (new) | CLI entry — argparse, temp dir lifecycle, orchestration |
| `app/agents/workflow.py` (modify) | Preserve raw LLM output in decision/context/task nodes |
| `app/experiment/runner.py` (modify) | Data isolation, output extraction, scoring fixes, per-case results |
| `app/experiment/test_data.py` (modify) | Seed parameter for reproducibility |
| `config/evaluation_config.json` (modify) | Add scenario-type task_concepts |
| `tests/test_experiment_runner.py` (new) | Tests for runner evaluation fixes |

---

### Task 1: Fix evaluation_config.json type mismatch

**Files:**
- Modify: `config/evaluation_config.json`

- [ ] **Step 1: Add scenario-type task_concepts**

Replace entire `config/evaluation_config.json` with:

```json
{
  "type_patterns": {
    "meeting": ["会议", "meeting", "评审", "沟通会"],
    "travel": ["出差", "travel", "行程"],
    "shopping": ["购物", "shopping", "采购"],
    "contact": ["联系", "contact", "电话"],
    "schedule_check": ["日程", "安排", "查询", "会议"],
    "event_add": ["添加", "创建", "设置", "新建"],
    "event_delete": ["取消", "删除", "移除"],
    "general": []
  },
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

- [ ] **Step 2: Commit**

```bash
git add config/evaluation_config.json
git commit -m "fix(eval): add scenario-type task_concepts to evaluation config"
```

---

### Task 2: Add seed parameter to TestDataGenerator

**Files:**
- Modify: `app/experiment/test_data.py:42-67`
- Test: `tests/test_experiment_runner.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_runner.py`:

```python
from app.experiment.test_data import TestDataGenerator


def test_seed_reproducibility():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=42)
    assert [c["input"] for c in cases_a] == [c["input"] for c in cases_b]


def test_seed_produces_different_without_seed():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=99)
    inputs_a = [c["input"] for c in cases_a]
    inputs_b = [c["input"] for c in cases_b]
    # With high probability, different seeds produce different orderings
    # (not guaranteed but extremely likely with 5 samples from 24 templates)
    assert inputs_a != inputs_b or len(set(inputs_a)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_experiment_runner.py::test_seed_reproducibility -v`
Expected: FAIL — `generate_test_cases()` doesn't accept `seed` keyword

- [ ] **Step 3: Implement seed parameter**

In `app/experiment/test_data.py`, change `generate_test_cases` signature:

```python
def generate_test_cases(self, count: int = 20, seed: int | None = None) -> List[Dict]:
    if seed is not None:
        random.seed(seed)
    test_cases = []
    # ... rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_experiment_runner.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add app/experiment/test_data.py tests/test_experiment_runner.py
git commit -m "feat(experiment): add seed parameter to TestDataGenerator"
```

---

### Task 3: Preserve raw LLM output in workflow

**Files:**
- Modify: `app/agents/workflow.py:94-118` (context_node), `app/agents/workflow.py:120-147` (task_node), `app/agents/workflow.py:149-178` (strategy_node)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_runner.py`:

```python
def test_raw_preserved_in_context_node():
    """Context node should preserve raw LLM output."""
    from unittest.mock import MagicMock
    from app.agents.workflow import AgentWorkflow

    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"time": "10:00", "location": "home"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory = MagicMock()
    workflow.memory.search.return_value = []
    workflow.memory.get_history.return_value = []
    workflow.memory.chat_model = mock_chat

    from app.agents.state import AgentState
    from langchain_core.messages import HumanMessage
    state: AgentState = {
        "messages": [HumanMessage(content="现在几点")],
        "context": {},
        "task": {},
        "decision": {},
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert result["context"].get("raw") is not None


def test_raw_preserved_in_strategy_node():
    """Strategy node should preserve raw LLM output."""
    from unittest.mock import MagicMock, patch
    from app.agents.workflow import AgentWorkflow

    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"should_remind": false, "reasoning": "test"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory = MagicMock()
    workflow.memory.chat_model = mock_chat

    from app.agents.state import AgentState
    from langchain_core.messages import HumanMessage

    # Patch JSONStore.read to return minimal strategies
    with patch("app.agents.workflow.JSONStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.read.return_value = {"reminder_weights": {"default": 1.0}}
        mock_store_cls.return_value = mock_store

        state: AgentState = {
            "messages": [HumanMessage(content="test")],
            "context": {},
            "task": {},
            "decision": {},
            "memory_mode": "keyword",
            "result": None,
            "event_id": None,
        }
        result = workflow._strategy_node(state)
        assert result["decision"].get("raw") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_experiment_runner.py::test_raw_preserved_in_context_node tests/test_experiment_runner.py::test_raw_preserved_in_strategy_node -v`
Expected: FAIL — `raw` key not present

- [ ] **Step 3: Add raw preservation to context_node**

In `app/agents/workflow.py`, in `_context_node`, after `context = json.loads(result)` block (line 105-109), add before the return:

```python
        context["raw"] = result
```

- [ ] **Step 4: Add raw preservation to task_node**

In `_task_node`, after `task = json.loads(result)` block (line 137-141), add before the return:

```python
        task["raw"] = result
```

- [ ] **Step 5: Add raw preservation to strategy_node**

In `_strategy_node`, after `decision = json.loads(result)` block (line 167-172), add before the return:

```python
        decision["raw"] = result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_experiment_runner.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add app/agents/workflow.py tests/test_experiment_runner.py
git commit -m "fix(workflow): preserve raw LLM output in agent nodes"
```

---

### Task 4: Fix evaluation metrics in runner

**Files:**
- Modify: `app/experiment/runner.py`
- Modify: `tests/test_experiment_runner.py`

- [ ] **Step 1: Write failing tests for split_words bigram fix**

Append to `tests/test_experiment_runner.py`:

```python
from app.experiment.runner import _evaluate_semantic_accuracy


def test_split_words_uses_bigrams():
    """Chinese text should produce bigram-level tokens, not single chars."""
    score = _evaluate_semantic_accuracy(
        "提醒我明天开会",
        "schedule_check",
        "明天有个会议安排",
    )
    # "明天" should match as a bigram unit
    # Score should be > 0 due to bigram overlap
    assert score > 0


def test_semantic_accuracy_with_raw_output():
    """Scoring should work on raw LLM output containing reasoning."""
    raw = '{"reasoning": "用户查询涉及日程安排和会议时间", "should_remind": false}'
    score = _evaluate_semantic_accuracy(
        "明天有什么安排",
        "schedule_check",
        raw,
    )
    # "安排" bigram should match between input and output
    assert score > 0


def test_context_relatedness_schedule_check():
    """schedule_check type should have non-zero relatedness with concept keywords."""
    from app.experiment.runner import ExperimentRunner
    runner = ExperimentRunner(config_dir="config")
    score = runner._evaluate_context_relatedness(
        "明天有什么安排",
        "schedule_check",
        "你的日程安排如下：明天下午三点有个会议提醒",
    )
    assert score > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_experiment_runner.py::test_split_words_uses_bigrams tests/test_experiment_runner.py::test_context_relatedness_schedule_check -v`
Expected: FAIL — single-char overlap and type mismatch

- [ ] **Step 3: Fix split_words to use bigram approach**

In `app/experiment/runner.py`, replace the `split_words` inner function inside `_evaluate_semantic_accuracy`:

```python
    def split_words(text: str) -> set:
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        english_words = set(re.findall(r"[a-zA-Z]+", text.lower()))
        chinese_bigrams = {chinese_chars[i] + chinese_chars[i + 1] for i in range(len(chinese_chars) - 1)}
        return chinese_bigrams | english_words
```

- [ ] **Step 4: Fix scoring formula**

In the same function, replace the overlap scoring block:

```python
    overlap = len(input_words & output_words)
    if overlap > 0:
        score += min(0.4, overlap * 0.05)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_experiment_runner.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add app/experiment/runner.py tests/test_experiment_runner.py
git commit -m "fix(eval): use bigram tokenization and fix scoring formula"
```

---

### Task 5: Data isolation and output extraction in runner

**Files:**
- Modify: `app/experiment/runner.py:238-299` (`_run_method`, `_get_latest_output`)
- Modify: `tests/test_experiment_runner.py`

- [ ] **Step 1: Write failing test for data_dir parameter**

Append to `tests/test_experiment_runner.py`:

```python
def test_run_method_uses_isolated_data_dir(tmp_path):
    """_run_method should accept and use a custom data_dir."""
    from unittest.mock import MagicMock, patch
    from app.experiment.runner import ExperimentRunner

    runner = ExperimentRunner(data_dir=str(tmp_path), config_dir="config")

    # Patch create_workflow to capture the data_dir it receives
    captured_dirs = []
    original_create = patch("app.experiment.runner.create_workflow")

    with original_create as mock_create:
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = ("处理完成", "test_id")
        mock_create.return_value = mock_workflow

        runner._run_method("keyword", [{"input": "测试", "type": "general"}], data_dir=str(tmp_path / "iso"))
        mock_create.assert_called_once_with(str(tmp_path / "iso"), memory_mode="keyword")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_experiment_runner.py::test_run_method_uses_isolated_data_dir -v`
Expected: FAIL — `_run_method` doesn't accept `data_dir`

- [ ] **Step 3: Add data_dir parameter to _run_method**

Change `_run_method` signature and body in `app/experiment/runner.py`:

```python
    def _run_method(self, method: str, test_cases: List[Dict], data_dir: str | None = None) -> Dict:
        effective_data_dir = data_dir if data_dir is not None else self.data_dir
        workflow = create_workflow(effective_data_dir, memory_mode=method)
        # ... rest of method unchanged
```

- [ ] **Step 4: Update _get_latest_output to accept data_dir**

Change `_get_latest_output`:

```python
    def _get_latest_output(self, data_dir: str | None = None) -> str:
        effective_dir = data_dir if data_dir is not None else self.data_dir
        events_store = JSONStore(effective_dir, "events.json", list)
        # ... rest unchanged
```

- [ ] **Step 5: Rewrite _run_method body — combine output extraction + per_case collection**

Replace the entire `_run_method` body. This single step combines output extraction (raw LLM), per_case results, and data_dir support:

Add new method `_extract_scoring_output`:

```python
    def _extract_scoring_output(self, result: str, data_dir: str | None = None) -> str:
        effective_dir = data_dir if data_dir is not None else self.data_dir
        events_store = JSONStore(effective_dir, "events.json", list)
        events = events_store.read()
        if events:
            last_event = events[-1]
            decision = last_event.get("decision", {})
            if isinstance(decision, str):
                return decision
            raw = decision.get("raw", "")
            if raw:
                return raw
            reasoning = decision.get("reasoning", "")
            content = decision.get("content", "")
            if reasoning or content:
                return f"{reasoning} {content}".strip()
        return result if result else self._get_latest_output(data_dir=effective_dir)
```

Replace entire `_run_method`:

```python
    def _run_method(self, method: str, test_cases: List[Dict], data_dir: str | None = None) -> Dict:
        effective_data_dir = data_dir if data_dir is not None else self.data_dir
        workflow = create_workflow(effective_data_dir, memory_mode=method)

        latencies = []
        task_completions = []
        semantic_accuracies = []
        context_relatedness_scores = []
        per_case = []

        for case in test_cases:
            start_time = time.time()
            try:
                result, event_id = workflow.run(case["input"])
                elapsed = (time.time() - start_time) * 1000
                latencies.append(elapsed)
                task_completions.append(1)
                actual_output = self._extract_scoring_output(result, effective_data_dir)
                accuracy = self._evaluate_semantic_accuracy(case["input"], case["type"], actual_output)
                semantic_accuracies.append(accuracy)
                relatedness = self._evaluate_context_relatedness(case["input"], case["type"], actual_output)
                context_relatedness_scores.append(relatedness)
                per_case.append({
                    "input": case["input"],
                    "type": case["type"],
                    "output": actual_output[:200],
                    "latency_ms": elapsed,
                    "semantic_accuracy": accuracy,
                    "context_relatedness": relatedness,
                })
            except Exception as e:
                logger.warning(f"Experiment run failed for case '{case.get('input', 'unknown')}': {e}")
                latencies.append(0)
                task_completions.append(0)
                semantic_accuracies.append(0)
                context_relatedness_scores.append(0)
                per_case.append({
                    "input": case["input"],
                    "type": case["type"],
                    "output": "",
                    "latency_ms": 0,
                    "semantic_accuracy": 0,
                    "context_relatedness": 0,
                    "error": str(e),
                })

        return {
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "task_completion_rate": sum(task_completions) / len(task_completions) if task_completions else 0,
            "semantic_accuracy": sum(semantic_accuracies) / len(semantic_accuracies) if semantic_accuracies else 0,
            "context_relatedness": sum(context_relatedness_scores) / len(context_relatedness_scores) if context_relatedness_scores else 0,
            "per_case": per_case,
        }
```

- [ ] **Step 6: Update run_comparison to pass data_dir and seed**

In `run_comparison`, update the loop:

```python
    def run_comparison(
        self, test_cases: List[Dict[str, str]], methods: Optional[List[str]] = None, data_dir: str | None = None, seed: int | None = None
    ) -> Dict[str, Any]:
        # ... validation unchanged ...
        results = {
            "timestamp": datetime.now().isoformat(),
            "test_cases": len(test_cases),
            "methods": methods,
            "seed": seed,
            "metrics": {},
        }
        for method in methods:
            method_results = self._run_method(method, test_cases, data_dir=data_dir)
            results["metrics"][method] = method_results
        self._save_results(results)
        return results
```

- [ ] **Step 7: Update generate_report for Markdown table**

Replace `generate_report`:

```python
    def generate_report(self) -> str:
        results_store = JSONStore(self.data_dir, "experiment_results.json", list)
        results = results_store.read()
        if not results:
            return "暂无实验数据"
        latest = results[-1]
        report = "# 实验对比报告\n\n"
        report += f"时间: {latest['timestamp']}\n"
        report += f"测试用例数: {latest['test_cases']}\n"
        if "seed" in latest:
            report += f"随机种子: {latest['seed']}\n"
        report += "\n## 方法对比\n\n"
        report += "| 方法 | 平均延迟(ms) | 完成率 | 语义准确率 | 上下文相关度 |\n"
        report += "|------|-------------|--------|-----------|-------------|\n"
        for method, metrics in latest["metrics"].items():
            report += f"| {method} | {metrics['avg_latency_ms']:.1f} | {metrics['task_completion_rate']*100:.1f}% | {metrics.get('semantic_accuracy', 0)*100:.1f}% | {metrics.get('context_relatedness', 0)*100:.1f}% |\n"
        return report
```

- [ ] **Step 8: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add app/experiment/runner.py tests/test_experiment_runner.py
git commit -m "feat(experiment): data isolation, raw output extraction, per-case results"
```

---

### Task 6: Create run_exp.py entry script

**Files:**
- Create: `run_exp.py`

- [ ] **Step 1: Create the entry script**

Create `run_exp.py` at project root:

```python
import argparse
import shutil
import json
from datetime import datetime
from pathlib import Path
from app.experiment.runner import ExperimentRunner
from app.experiment.test_data import TestDataGenerator
from app.storage.init_data import init_storage
from app.storage.json_store import JSONStore


def main():
    parser = argparse.ArgumentParser(description="运行记忆方式对比实验")
    parser.add_argument("--methods", nargs="+", default=["keyword", "llm_only", "embeddings", "memorybank"])
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
        init_storage(str(temp_dir))

        # Remove experiment_results from temp (don't need it there)
        (temp_dir / "experiment_results.json").unlink(missing_ok=True)

        method_results = runner._run_method(method, test_cases, data_dir=str(temp_dir))
        combined_results["metrics"][method] = method_results

        metrics = method_results
        print(f"  Latency: {metrics['avg_latency_ms']:.1f}ms")
        print(f"  Completion: {metrics['task_completion_rate']*100:.1f}%")
        print(f"  Semantic: {metrics.get('semantic_accuracy', 0)*100:.1f}%")
        print(f"  Relatedness: {metrics.get('context_relatedness', 0)*100:.1f}%")

        shutil.rmtree(temp_dir, ignore_errors=True)

    # Save combined results once (all methods in one entry)
    results_store = JSONStore("data", "experiment_results.json", list)
    results_store.append(combined_results)

    print("\n" + "=" * 50)
    print(runner.generate_report())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run lint**

Run: `ruff check run_exp.py app/experiment/runner.py app/experiment/test_data.py app/agents/workflow.py`
Expected: No errors (or auto-fixable warnings)

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add run_exp.py
git commit -m "feat(experiment): add run_exp.py CLI entry script with data isolation"
```

---

### Task 7: Integration smoke test

**Files:** None new

- [ ] **Step 1: Run a minimal experiment with 2 test cases on keyword only**

Run: `python run_exp.py --methods keyword --count 2 --seed 42`
Expected: Completes without error, prints metrics table. Keyword method should show ~100% completion.

- [ ] **Step 2: Run full experiment on all 4 methods with 5 test cases**

Run: `python run_exp.py --count 5 --seed 42`
Expected: All 4 methods complete, results differ across methods. Latency should rank: keyword < embeddings < llm_only. MemoryBank may vary.

- [ ] **Step 3: Verify data isolation — check no pollution in main data/**

Run: `python -c "import json; data=json.load(open('data/events.json')); print(f'Events in main data: {len(data)}')"`
Expected: Event count unchanged from before experiment (no new events added to main data/)

- [ ] **Step 4: Verify results saved**

Run: `python -c "import json; data=json.load(open('data/experiment_results.json')); print(f'Experiment runs: {len(data)}'); print(f'Latest seed: {data[-1].get(\"seed\", \"N/A\")}')"`
Expected: Shows total runs including new ones, seed=42

- [ ] **Step 5: Final lint + test**

Run: `ruff check . && pytest tests/ -v`
Expected: Clean
