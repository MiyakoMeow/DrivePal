# 消融实验框架 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建三组消融实验框架（安全性组 / 架构组 / 个性化组），包含场景合成、变体运行、LLM-as-Judge 评分、指标统计与报告。

**架构：** `experiments/ablation/` 为顶层 CLI 入口（`python -m`，非 pytest runner）。各实验组独立模块，共享 `ablation_runner`（变体调度）和 `judge`（评分）。最少生产代码改动——仅 `postprocess_decision` 增加修改追踪和环境变量检查。

**技术栈：** Python 3.14, asyncio, argparse, jsonl, pydantic, ChatModel (现有)

---

## 文件结构总览

```
experiments/ablation/
├── __init__.py
├── __main__.py                # 入口
├── cli.py                     # argparse CLI
├── types.py                   # TestScenario, VariantResult, JudgeScores 等
├── scenario_synthesizer.py    # LLM 批量合成场景
├── ablation_runner.py         # 变体调度器（设置环境变量 → 运行 → 收集结果）
├── judge.py                   # LLM-as-Judge 评分 + 校准
├── safety_group.py            # 安全性组实验编排
├── architecture_group.py      # 架构组实验编排
├── personalization_group.py   # 个性化组实验编排
├── metrics.py                 # 指标计算
└── report.py                  # 结果表格/图表生成

tests/experiments/
├── __init__.py
├── test_scenario_synthesizer.py
├── test_judge.py
└── test_metrics.py

修改现有文件：
├── app/agents/rules.py        # postprocess_decision 增加 modifications + env 检查
├── app/agents/workflow.py     # _execution_node 记录 modifications；_strategy_node 检查 ABLATION_DISABLE_FEEDBACK
└── app/agents/prompts.py      # 新增 SINGLE_LLM_SYSTEM_PROMPT
```

---

## Phase 1：基础设施修改

### 任务 1.1：postprocess_decision 增加修改追踪与环境变量检查

**文件：**
- 修改：`app/agents/rules.py:224-249`

- [ ] **步骤 1：修改 postprocess_decision 签名和逻辑**

修改返回为 `tuple[dict, list[str]]`。记录每次修改的字段名。新增 `ABLATION_DISABLE_RULES` 检查——为 1 时直接返回原始 decision。

```python
import os

def postprocess_decision(decision: dict, driving_context: dict) -> tuple[dict, list[str]]:
    """在 LLM 决策后强制应用安全规则，不可绕过。

    Returns:
        (修改后的决策, 被修改的字段列表)
    """
    if os.getenv("ABLATION_DISABLE_RULES") == "1":
        return decision, []

    result = dict(decision)
    modifications: list[str] = []
    constraints = apply_rules(driving_context)

    if constraints.get("postpone", False):
        if result.get("should_remind", True):
            modifications.append("should_remind→false(postpone)")
        if result.get("reminder_content"):
            modifications.append("reminder_content→cleared(postpone)")
        result["should_remind"] = False
        result["reminder_content"] = ""

    allowed = constraints.get("allowed_channels")
    if allowed is not None:
        channels = result.get("allowed_channels", list(allowed))
        if isinstance(channels, list):
            filtered = [c for c in channels if c in allowed]
            if len(filtered) != len(channels):
                removed = set(channels) - set(filtered)
                modifications.append(f"allowed_channels −{removed}")
            result["allowed_channels"] = filtered or allowed

    if constraints.get("only_urgent", False):
        event_type = (result.get("type", "general") or "").lower()
        if event_type not in URGENT_TYPES:
            if result.get("should_remind", True):
                modifications.append("should_remind→false(only_urgent)")
            if result.get("reminder_content"):
                modifications.append("reminder_content→cleared(only_urgent)")
            result["should_remind"] = False
            result["reminder_content"] = ""

    return result, modifications
```

- [ ] **步骤 2：更新所有调用 postprocess_decision 的位置**

搜索 `postprocess_decision(` 调用：
- `app/agents/workflow.py:_execution_node` — 解包 tuple
- `app/agents/rules.py` 内部的测试/内部引用（如有）

```python
# workflow.py _execution_node 中：
if driving_ctx:
    decision, modifications = postprocess_decision(decision, driving_ctx)
    if stages is not None:
        stages.execution = {**(stages.execution or {}), "modifications": modifications}
```

- [ ] **步骤 3：更新测试**

`tests/test_rules.py` 中调用 `postprocess_decision` 的测试需适配新返回值。

- [ ] **步骤 4：运行测试验证**

```bash
uv run pytest tests/test_rules.py -v
```

预期：所有规则测试通过，返回 tuple 格式正确。

- [ ] **步骤 5：Commit**

```bash
git add app/agents/rules.py app/agents/workflow.py tests/test_rules.py
git commit -m "feat: add modifications tracking to postprocess_decision for ablation"
```

---

### 任务 1.2：_execution_node 记录 modifications 到 stages

**文件：**
- 修改：`app/agents/workflow.py:307-383`

- [ ] **步骤 1：解包 postprocess_decision 返回值**

已在任务 1.1 步骤 2 中完成。确认 `stages.execution` 字典在所有路径（禁止发送/延后/频次约束/成功）都包含 `modifications` 键：

```python
# 禁止发送路径：
stages.execution = {
    "content": None, "event_id": None,
    "result": result, "modifications": modifications,
}

# 延后路径：同上
# 频次约束路径：modifications 来自 postprocess_decision（即使后续频次拦截，规则修改仍需记录）
# 禁止发送路径：同上
# 延后路径：同上
# 成功路径：同上
```

- [ ] **步骤 2：运行规则相关测试**

```bash
uv run pytest tests/test_rules.py tests/stores/ -v -k "rule or frequency" -q
```

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: propagate modifications to WorkflowStages.execution"
```

---

### 任务 1.3：_strategy_node 增加 ABLATION_DISABLE_FEEDBACK 检查

**文件：**
- 修改：`app/agents/workflow.py:_strategy_node`（约 240-305 行区域）

- [ ] **步骤 1：在 feedback weights 注入前检查环境变量**

```python
import os

# 在 _strategy_node 中，读取 reminder_weights 之后、注入 prompt 之前：
if os.getenv("ABLATION_DISABLE_FEEDBACK") == "1":
    # 固定权重 0.5——所有类型均等
    reminder_weights = {"meeting": 0.5, "travel": 0.5, "shopping": 0.5, "contact": 0.5, "other": 0.5}
```

- [ ] **步骤 2：验证 env 变量传递**

```bash
ABLATION_DISABLE_FEEDBACK=1 uv run pytest tests/ -v -k "strategy" -q
```

检查 Strategy 阶段 prompt 中权重是否固定为 0.5。

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: add ABLATION_DISABLE_FEEDBACK env check to strategy node"
```

---

### 任务 1.4：增加 SINGLE_LLM_SYSTEM_PROMPT

**文件：**
- 修改：`app/agents/prompts.py`

- [ ] **步骤 1：新增提示词常量**

在 `prompts.py` 末尾添加。合并三个 Agent 职责为一个 prompt，输出要求 `{"context": {...}, "task": {...}, "decision": {...}}` 三字段 JSON。

**输出字段对应关系**：

| 字段 | 对应现有 Prompt | 输出内容 |
|------|----------------|---------|
| `context` | `CONTEXT_SYSTEM_PROMPT` | 时间/位置/交通/偏好/状态 JSON |
| `task` | `TASK_SYSTEM_PROMPT` | type (meeting/travel/shopping/contact/other), confidence, summary |
| `decision` | `STRATEGY_SYSTEM_PROMPT` | should_remind, timing, channel, content, is_urgent, postpone |

各字段 JSON schema 与现有三 Agent 输出完全一致——仅有结构差异（合并为一个 JSON），无字段增删。中文风格，含 `{current_datetime}` 占位符。

- [ ] **步骤 2：验证可导入**

```python
from app.agents.prompts import SINGLE_LLM_SYSTEM_PROMPT
```

- [ ] **步骤 3：Commit**

```bash
git add app/agents/prompts.py
git commit -m "feat: add SINGLE_LLM_SYSTEM_PROMPT for ablation architecture group"
```

---

## Phase 2：实验框架核心

### 任务 2.1：创建目录结构与类型定义

**文件：**
- 创建：`experiments/__init__.py`（空）
- 创建：`experiments/ablation/__init__.py`（空）
- 创建：`experiments/ablation/types.py`

- [ ] **步骤 1：创建 types.py**

```python
"""消融实验数据类型."""
from dataclasses import dataclass, field
from enum import Enum


class Variant(str, Enum):
    FULL = "full"
    NO_RULES = "no-rules"
    NO_PROB = "no-prob"
    SINGLE_LLM = "single-llm"
    NO_FEEDBACK = "no-feedback"


@dataclass
class TestScenario:
    id: str
    driving_context: dict
    user_query: str
    expected_decision: dict       # should_remind, channel, content, is_urgent
    expected_task_type: str
    safety_relevant: bool
    scenario_type: str


@dataclass
class VariantResult:
    scenario_id: str
    variant: Variant
    decision: dict          # 最终决策（含 should_remind, channel, content 等）
    result_text: str        # 执行结果文本
    event_id: str | None
    stages: dict            # WorkflowStages 序列化（含 context, task, decision, execution）
    latency_ms: float       # 端到端耗时（毫秒）
    modifications: list[str] = field(default_factory=list)  # 规则修改记录


@dataclass
class JudgeScores:
    scenario_id: str
    variant: Variant
    safety_score: int        # 1-5
    reasonableness_score: int
    overall_score: int
    violation_flags: list[str]
    explanation: str


@dataclass
class GroupResult:
    """一组实验的完整结果."""
    group: str               # "safety" | "architecture" | "personalization"
    variant_results: list[VariantResult]
    judge_scores: list[JudgeScores]
    metrics: dict
```

- [ ] **步骤 2：验证导入**

```python
from experiments.ablation.types import Variant, TestScenario, VariantResult
```

- [ ] **步骤 3：Commit**

```bash
git add experiments/
git commit -m "feat: add ablation experiment types and directory structure"
```

---

### 任务 2.2：场景合成器

**文件：**
- 创建：`experiments/ablation/scenario_synthesizer.py`

**思路**：
1. 按维度组合（scenario × fatigue × workload × task_type × has_passengers）生成 Prompt
2. 对每个组合调用 ChatModel（JSON mode），要求返回 `{driving_context, user_query, expected_decision, expected_task_type}`
3. 缓存到 `data/experiments/scenarios.jsonl`——已存在则跳过（幂等）
4. 提供 `synthesize_scenarios(seed, output_path)` 和 `load_scenarios(path)` 两个公共函数

**关键细节**：
- 使用 `get_chat_model()` 获取 LLM，temperature=0.7（需要多样性）
- `ABLATION_SEED` 环境变量控制维度组合和 JSONL 顺序（固定 `random.seed`）
- `safety_relevant` 字段自动判定：`scenario in [highway,city_driving] or fatigue>0.7 or workload==overloaded → True`
- 精选策略：100-150 场景，按 §3.4 分层抽样（安全关键 50 + 多样化 50 + 个性化候选 20）

**公共接口**：
```python
async def synthesize_scenarios(output_path: Path, count: int = 120) -> int:
    """合成场景，返回成功数。幂等——已缓存的跳过。"""

def load_scenarios(path: Path) -> list[TestScenario]:
    """从 JSONL 加载场景。"""

def sample_scenarios(scenarios: list[TestScenario], n: int, *, safety_only: bool = False, seed: int = 42) -> list[TestScenario]:
    """分层随机抽样。"""
```

- [ ] **步骤 1：实现 synthesize_scenarios**
- [ ] **步骤 2：实现 load_scenarios / sample_scenarios**
- [ ] **步骤 3：手动测试**

```bash
uv run python -c "
import asyncio
from pathlib import Path
from experiments.ablation.scenario_synthesizer import synthesize_scenarios, load_scenarios
asyncio.run(synthesize_scenarios(Path('data/experiments/scenarios.jsonl'), count=10))
scenarios = load_scenarios(Path('data/experiments/scenarios.jsonl'))
print(f'Loaded {len(scenarios)} scenarios')
print(scenarios[0])
"
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py
git commit -m "feat: add scenario synthesizer for ablation experiments"
```

---

### 任务 2.3：消融运行器

**文件：**
- 创建：`experiments/ablation/ablation_runner.py`

**思路**：
```python
import os
import time

class AblationRunner:
    def __init__(self, user_id: str):
        """每组实验独立 user_id（spec §6.3）。"""
        self.user_id = user_id
        self._original_env: dict[str, str] = {}

    def _set_env(self, **kwargs: str) -> None:
        """设置环境变量（当前进程，非子进程）。备份用于恢复。"""
        for k, v in kwargs.items():
            self._original_env.setdefault(k, os.environ.get(k, ""))
            os.environ[k] = v

    def _restore_env(self) -> None:
        """恢复原始环境变量。"""
        for k, v in self._original_env.items():
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        self._original_env.clear()

    async def run_variant(
        self,
        scenario: TestScenario,
        variant: Variant,
    ) -> VariantResult:
        """单一变体运行。

        所有变体运行均在当前进程事件循环内完成。
        os.environ 临时设置——在当前协程睡眠/await 期间不会被其他协程修改
        （因为 run_batch 顺序执行，同一时间只有一个变体在运行）。
        """
        # 设置环境变量
        if variant == Variant.NO_RULES:
            self._set_env(ABLATION_DISABLE_RULES="1")
        elif variant == Variant.NO_PROB:
            self._set_env(PROBABILISTIC_INFERENCE_ENABLED="0")
        elif variant == Variant.NO_FEEDBACK:
            self._set_env(ABLATION_DISABLE_FEEDBACK="1")

        try:
            t0 = time.perf_counter()
            if variant == Variant.SINGLE_LLM:
                result = await self._run_single_llm(scenario)
            else:
                result = await self._run_agent_workflow(scenario)
            result.latency_ms = (time.perf_counter() - t0) * 1000
            return result
        finally:
            self._restore_env()
```

**单 LLM 路径**：
```python
async def _run_single_llm(self, scenario: TestScenario) -> VariantResult:
    chat = get_chat_model()
    prompt = SINGLE_LLM_SYSTEM_PROMPT.format(current_datetime=...)
    user_msg = json.dumps({
        "query": scenario.user_query,
        "context": scenario.driving_context,
    })
    response = await chat.generate(system_prompt=prompt, prompt=user_msg, json_mode=True)
    output = json.loads(response)
    return VariantResult(
        scenario_id=scenario.id,
        variant=Variant.SINGLE_LLM,
        decision=output.get("decision", {}),
        result_text="",
        event_id=None,
        stages={
            "context": output.get("context", {}),
            "task": output.get("task", {}),
            "decision": output.get("decision", {}),
            "execution": {},
        },
        latency_ms=0.0,
    )
```

**四 Agent 路径**：
```python
async def _run_agent_workflow(self, scenario: TestScenario) -> VariantResult:
    from app.agents.workflow import AgentWorkflow
    from app.memory.singleton import get_memory_module

    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_mode=MemoryMode.MEMORY_BANK,
        memory_module=mm,
        current_user=self.user_id,
    )
    result, event_id, stages = await workflow.run_with_stages(
        scenario.user_query,
        driving_context=scenario.driving_context,
    )
    return VariantResult(
        scenario_id=scenario.id,
        variant=Variant.FULL,  # caller overwrites
        decision=stages.decision,
        result_text=result,
        event_id=event_id,
        stages={
            "context": stages.context,
            "task": stages.task,
            "decision": stages.decision,
            "execution": stages.execution,
        },
        latency_ms=0.0,
        modifications=stages.execution.get("modifications", []) if stages.execution else [],
    )
```

**用户 ID 分配**（各组实验编排中传入）：
```python
# safety_group.py:
runner = AblationRunner(user_id="experiment-safety")

# architecture_group.py:
runner = AblationRunner(user_id="experiment-architecture")

# personalization_group.py:
runner = AblationRunner(user_id="experiment-personalization")
```

- [ ] **步骤 1：实现 AblationRunner 类**
- [ ] **步骤 2：手动测试单个场景**

```bash
uv run python -c "
import asyncio
from experiments.ablation.types import TestScenario, Variant
from experiments.ablation.ablation_runner import AblationRunner
# ... test with a simple scenario
"
```

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/ablation_runner.py
git commit -m "feat: add ablation runner with variant dispatch"
```

---

### 任务 2.4：CLI 入口

**文件：**
- 创建：`experiments/ablation/cli.py`
- 创建：`experiments/ablation/__main__.py`

- [ ] **步骤 1：实现 cli.py**

```python
"""消融实验命令行接口."""
import argparse
from pathlib import Path

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DrivePal-2 消融实验")
    parser.add_argument("--group", choices=["safety", "architecture", "personalization", "all"],
                        default="all", help="实验组")
    parser.add_argument("--synthesize-only", action="store_true", help="仅合成场景")
    parser.add_argument("--judge-only", action="store_true", help="仅重新评分")
    parser.add_argument("--data-dir", default="data/experiments")
    parser.add_argument("--seed", type=int, default=42)
    return parser

async def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    # ... dispatch to groups
```

- [ ] **步骤 2：实现 __main__.py**

```python
"""python -m experiments.ablation 入口."""
import asyncio
from experiments.ablation.cli import main

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 3：验证 CLI**

```bash
uv run python -m experiments.ablation --help
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/cli.py experiments/ablation/__main__.py
git commit -m "feat: add CLI entry point for ablation experiments"
```

---

## Phase 3：Judge 模块

### 任务 3.1：LLM-as-Judge 评分模块

**文件：**
- 创建：`experiments/ablation/judge.py`

**思路**：
```python
class Judge:
    """LLM-as-Judge 评分器。"""

    async def score_variant(
        self, scenario: TestScenario, result: VariantResult, *, blind: bool = True
    ) -> JudgeScores:
        """评分单个变体输出。"""
        # 构建 prompt：场景上下文 + 变体决策 + 评分维度
        # 调用 ChatModel（JSON mode），temperature=0.0
        # 解析 JSON → JudgeScores

    async def score_batch(
        self, scenario: TestScenario, results: list[VariantResult], *, blind: bool = True
    ) -> list[JudgeScores]:
        """盲评多个变体——shuffle 顺序后逐个评分。"""
        # 每组场景评 3 次，取中位数

    def compute_calibration(
        self, annotated: list[tuple[TestScenario, JudgeScores]], human_scores: list[dict]
    ) -> float:
        """计算 Judge 与人工标注的 Cohen's κ。"""
```

**Judge Prompt 设计**（§5.2 + §5.3）：

Judge 接收 JSON 格式输入：
```json
{
  "scenario": {"user_query": "...", "driving_context": {...}, "expected_decision": {...}},
  "variant_output": {"decision": {...}, "stages": {...}}
}
```

要求输出：
```json
{
  "safety_score": <int 1-5>,
  "reasonableness_score": <int 1-5>,
  "overall_score": <int 1-5>,
  "violation_flags": ["<flag>", ...],
  "explanation": "<中文解释>"
}
```

中间阶段评分用独立 prompt（§5.3），分 Context/Task/Strategy 三个维度各 1-5 分。

**Judge 模型选择**（§5.1）：
```python
def _get_judge_model() -> ChatModel:
    """实验用 Judge 模型——优先 JUDGE_MODEL，否则 fallback default。"""
    from app.models.settings import NoJudgeModelConfiguredError
    try:
        return get_judge_model()
    except NoJudgeModelConfiguredError:
        return get_chat_model()
```

**校准流程**（§5.4）：
```python
async def calibrate(
    calibration_scenarios: list[TestScenario],  # 30 个校准集
    human_labels: dict[str, dict],              # scenario_id → expected_decision
    holdout_scenarios: list[TestScenario],       # 20 个留存集（不参与 prompt 调整）
    max_iterations: int = 3,
) -> dict:
    """校准 Judge prompt，返回 {kappa_calibration, kappa_holdout}。

    步骤：
    1. 校准集上评分 → 计算 κ
    2. 若 κ < 0.7 且 iterations < max：调整 prompt → 回到步骤 1
    3. 若 3 轮后 κ 仍 < 0.7：换 Judge 模型（model_groups.smart），重跑
    4. 校准通过后，留存集上计算最终 κ 作为报告值
    """
```

- [ ] **步骤 1：实现 Judge 类 + 核心评分 prompt**
- [ ] **步骤 2：实现中间阶段独立评分（Judge.score_stages）**
- [ ] **步骤 3：实现校准流程**
- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/judge.py
git commit -m "feat: add LLM-as-Judge scoring module"
```

---

## Phase 4：三组实验

### 任务 4.1：安全性组实验

**文件：**
- 创建：`experiments/ablation/safety_group.py`

**思路**：编排安全性组实验流程。
```python
async def run_safety_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[TestScenario],
    output_dir: Path,
) -> GroupResult:
    """安全性组实验。

    变体: FULL, NO_RULES, NO_PROB
    场景: 仅 safety_relevant=True，~50 个
    指标: 安全合规率, 规则拦截率, 误拦率, 决策综合质量
    """
    variants = [Variant.FULL, Variant.NO_RULES, Variant.NO_PROB]
    safety_scenarios = [s for s in scenarios if s.safety_relevant]

    results = await runner.run_batch(safety_scenarios, variants)
    scores = []
    for scenario in safety_scenarios:
        scenario_results = [r for r in results if r.scenario_id == scenario.id]
        batch_scores = await judge.score_batch(scenario, scenario_results)
        scores.extend(batch_scores)

    # 计算指标
    metrics = compute_safety_metrics(scores, results, safety_scenarios)
    return GroupResult(group="safety", variant_results=results, judge_scores=scores, metrics=metrics)
```

- [ ] **步骤 1：实现 run_safety_group**
- [ ] **步骤 2：Commit**

---

### 任务 4.2：架构组实验

**文件：**
- 创建：`experiments/ablation/architecture_group.py`

**思路**：与安全性组类似。变体 FULL vs SINGLE_LLM。场景为非安全关键 ~50 个。额外收集中间阶段评分（`judge.score_stages()`）。

- [ ] **步骤 1：实现 run_architecture_group**
- [ ] **步骤 2：Commit**

---

### 任务 4.3：个性化组实验

**文件：**
- 创建：`experiments/ablation/personalization_group.py`

**思路**：20 轮序列实验，变体 FULL vs NO_FEEDBACK。

```python
async def run_personalization_group(
    runner: AblationRunner,
    scenarios: list[TestScenario],  # 20 个
    output_dir: Path,
) -> GroupResult:
    """个性化组实验。

    20 轮，4 阶段偏好切换。每轮：
    1. 运行 FULL + NO_FEEDBACK
    2. 模拟反馈 → 直接调 feedback API 更新权重
    3. 记录权重快照
    """
    stages = [
        ("high-freq", 1, 5),     # 偏好高频率，accept should_remind=true
        ("silent", 6, 10),       # 偏好静默，仅 accept urgent
        ("visual-detail", 11, 15),  # 偏好视觉详细
        ("mixed", 16, 20),       # 混合，随机 accept/ignore
    ]
    # ... per-round logic
```

**反馈模拟函数**（§4.3 表）：
```python
def simulate_feedback(decision: dict, stage: str, rng: random.Random) -> str:
    """根据阶段判定 accept/ignore。"""
    if stage == "high-freq":
        return "accept" if decision.get("should_remind") else "ignore"
    elif stage == "silent":
        return "accept" if decision.get("should_remind") and decision.get("is_urgent") else "ignore"
    elif stage == "visual-detail":
        return "accept" if decision.get("channel") == "visual" else "ignore"
    elif stage == "mixed":
        return "accept" if rng.random() < 0.5 else "ignore"
```

**反馈权重更新**（进程内直接操作 TOMLStore，不依赖 HTTP/GraphQL）：
```python
async def update_feedback_weight(
    user_id: str, event_id: str, action: Literal["accept", "ignore"]
) -> None:
    """模拟 submitFeedback 的权重更新逻辑。

    直接读写 strategies.toml，不经过 GraphQL resolver。
    逻辑与 mutation.py submit_feedback 中的权重更新完全一致。
    """
    from app.memory.singleton import get_memory_module
    from app.config import user_data_dir
    from app.storage.toml_store import TOMLStore
    from app.memory.types import MemoryMode

    mm = get_memory_module()
    mode = MemoryMode.MEMORY_BANK
    event_type = await mm.get_event_type(event_id, mode=mode, user_id=user_id)
    if not event_type:
        return  # event 不存在时静默跳过

    user_dir = user_data_dir(user_id)
    strategy_store = TOMLStore(
        user_dir=user_dir, filename="strategies.toml", default_factory=dict,
    )
    current = await strategy_store.read()
    weights = dict(current.get("reminder_weights", {}))
    delta = 0.1 if action == "accept" else -0.1
    weights[event_type] = max(0.1, min(1.0, weights.get(event_type, 0.5) + delta))
    await strategy_store.update("reminder_weights", weights)
```

此函数在 `personalization_group.py` 中定义，每轮变体运行后调用。不新增生产代码文件。

- [ ] **步骤 1：实现 run_personalization_group + simulate_feedback**
- [ ] **步骤 2：Commit**

---

## Phase 5：指标与报告

### 任务 5.1：指标计算

**文件：**
- 创建：`experiments/ablation/metrics.py`

**思路**：
```python
def compute_safety_metrics(
    scores: list[JudgeScores], results: list[VariantResult], scenarios: list[TestScenario]
) -> dict:
    """安全性组指标。返回: {compliance_rate, interception_rate, false_positive_rate, quality_avg, ...}"""

def compute_quality_metrics(scores: list[JudgeScores]) -> dict:
    """决策质量指标。返回: {overall_avg, json_compliance_rate, latency_p50, latency_p90, ...}"""

def compute_preference_metrics(
    rounds: list[dict],  # {round, variant, decision, expected_preference, weight_snapshot}
) -> dict:
    """个性化指标。返回: {matching_rate, convergence_round, stability_std, ...}"""

def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """效应量计算。"""
```

- [ ] **步骤 1：实现所有指标函数**
- [ ] **步骤 2：Commit**

---

### 任务 5.2：报告生成

**文件：**
- 创建：`experiments/ablation/report.py`

**思路**：输出 HTML 报告和 JSON 数据。LaTeX 表格和 matplotlib 图表由用户离线生成。

```python
def render_report(results: dict[str, GroupResult], output_dir: Path) -> None:
    """生成 HTML 报告 + JSON 原始数据。

    输出：
    - results/safety.json, results/architecture.json, results/personalization.json — 原始数据
    - report.html — 汇总报告（表格 + JSON 嵌入）
    """
```

JSON 中包含指标表格所需的所有数据（均值、标准差、Cohen's d），可直接用于论文插入。

- [ ] **步骤 1：实现 render_report**
- [ ] **步骤 2：Commit**

---

## Phase 6：单元测试

### 任务 6.1：框架单元测试

**文件：**
- 创建：`tests/experiments/__init__.py`
- 创建：`tests/experiments/test_scenario_synthesizer.py`
- 创建：`tests/experiments/test_judge.py`
- 创建：`tests/experiments/test_metrics.py`
- 创建：`tests/experiments/conftest.py`

**测试清单**：

| 测试文件 | 测试内容 |
|---------|---------|
| `test_scenario_synthesizer.py` | load_scenarios 格式验证；sample_scenarios 分层正确性；safety_relevant 自动判定 |
| `test_judge.py` | JudgeScores JSON 解析；score_batch shuffle 盲评；compute_calibration Cohen's κ 计算；Judge 输出格式正确性 |
| `test_metrics.py` | cohens_d 计算；safety_metrics 边界情况（全合规/全违规）；preference_metrics 收敛判定 |
| `conftest.py` | mock ChatModel fixture（返回预定义 JSON）；mock AgentWorkflow fixture |

所有单元测试用 mock LLM，**不标记 `llm`**（mock 不需要真实 LLM）。入 CI，随 `uv run pytest` 自动运行。

- [ ] **步骤 1：创建 conftest.py（mock fixtures）**
- [ ] **步骤 2：实现 test_scenario_synthesizer.py**
- [ ] **步骤 3：实现 test_judge.py**
- [ ] **步骤 4：实现 test_metrics.py**
- [ ] **步骤 5：运行全部测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 6：Commit**

---

## Phase 7：集成验证

### 任务 7.1：完整流程验证

**文件：**
- 修改：`experiments/ablation/cli.py`（完善 dispatch 逻辑）

- [ ] **步骤 1：合成少量场景**

```bash
uv run python -m experiments.ablation --synthesize-only
```

- [ ] **步骤 2：运行单组实验**

```bash
uv run python -m experiments.ablation --group safety
```

- [ ] **步骤 3：检查输出**

```bash
ls data/experiments/results/
cat data/experiments/results/safety.jsonl | head -3
```

- [ ] **步骤 4：运行 ruff + ty 检查**

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
```

- [ ] **步骤 5：Commit**

```bash
git add -A
git commit -m "feat: complete ablation experiment framework"
```
