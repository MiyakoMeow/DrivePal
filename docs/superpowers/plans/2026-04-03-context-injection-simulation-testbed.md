# 上下文注入与模拟测试工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 REST API 替换为 GraphQL API，新增驾驶上下文数据注入、轻量规则引擎、场景预设管理，并将 WebUI 改造为模拟测试工作台。

**Architecture:** 请求级上下文注入（DrivingContext 随 query 传入），AgentWorkflow 按需跳过 LLM 推断上下文；轻量规则引擎在 Task Node 后、Strategy Node 前应用安全约束；全部 API 通过 Strawberry GraphQL 暴露；WebUI 重写为场景模拟+工作流调试页面。

**Tech Stack:** Python 3.13, FastAPI, Strawberry GraphQL, Pydantic v2, TOML 存储, 纯 HTML/CSS/JS

**Spec:** `docs/superpowers/specs/2026-04-02-context-injection-simulation-testbed-design.md`

---

## 文件结构

```
app/schemas/context.py          # 新建 — 上下文数据模型 + ScenarioPreset
app/api/main.py                 # 重写 — 删除 REST 端点，挂载 GraphQL
app/api/graphql_schema.py       # 新建 — Strawberry schema 定义
app/api/resolvers/__init__.py   # 新建
app/api/resolvers/query.py      # 新建 — Query resolvers
app/api/resolvers/mutation.py   # 新建 — Mutation resolvers
app/agents/state.py             # 修改 — AgentState 新增 driving_context, stages
app/agents/workflow.py          # 修改 — 新增 run_with_stages，改造 _context_node, _strategy_node
app/agents/rules.py             # 新建 — Rule 数据类 + 规则合并逻辑
app/agents/prompts.py           # 修改 — Strategy prompt 支持约束注入
app/storage/init_data.py        # 修改 — 新增 scenario_presets.toml 初始化
webui/index.html                # 重写 — 模拟测试工作台
tests/test_context_schemas.py   # 新建 — 上下文数据模型测试
tests/test_rules.py             # 新建 — 规则引擎测试
tests/test_graphql.py           # 新建 — GraphQL 端点测试（替代 test_api.py）
tests/test_api.py               # 删除 — 旧 REST API 测试
tests/test_chat.py              # 修改 — 更新 AgentState 构造以匹配新字段
```

---

### Task 1: 上下文数据模型

**Files:**
- Create: `app/schemas/context.py`
- Test: `tests/test_context_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_context_schemas.py
"""上下文数据模型测试."""

from app.schemas.context import (
    DriverState,
    GeoLocation,
    SpatioTemporalContext,
    TrafficCondition,
    DrivingContext,
    ScenarioPreset,
)


def test_driver_state_defaults():
    ds = DriverState()
    assert ds.emotion == "neutral"
    assert ds.workload == "normal"
    assert ds.fatigue_level == 0.0


def test_driver_state_invalid_emotion():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DriverState(emotion="happy")


def test_driver_state_invalid_workload():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DriverState(workload="extreme")


def test_driver_state_fatigue_bounds():
    import pytest
    from pydantic import ValidationError
    DriverState(fatigue_level=0.0)
    DriverState(fatigue_level=1.0)
    with pytest.raises(ValidationError):
        DriverState(fatigue_level=1.5)
    with pytest.raises(ValidationError):
        DriverState(fatigue_level=-0.1)


def test_geo_location_bounds():
    import pytest
    from pydantic import ValidationError
    GeoLocation(latitude=90.0, longitude=180.0)
    with pytest.raises(ValidationError):
        GeoLocation(latitude=91.0)
    with pytest.raises(ValidationError):
        GeoLocation(longitude=-181.0)


def test_spatio_temporal_context_defaults():
    st = SpatioTemporalContext()
    assert st.current_location == GeoLocation()
    assert st.destination is None
    assert st.eta_minutes is None


def test_traffic_condition_defaults():
    tc = TrafficCondition()
    assert tc.congestion_level == "smooth"
    assert tc.incidents == []
    assert tc.estimated_delay_minutes == 0


def test_traffic_condition_invalid_congestion():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TrafficCondition(congestion_level="unknown")


def test_driving_context_defaults():
    dc = DrivingContext()
    assert dc.scenario == "parked"
    assert dc.driver == DriverState()


def test_driving_context_to_dict():
    dc = DrivingContext(
        driver=DriverState(emotion="calm", fatigue_level=0.3),
        scenario="highway",
    )
    d = dc.model_dump()
    assert d["driver"]["emotion"] == "calm"
    assert d["scenario"] == "highway"


def test_scenario_preset_auto_id_and_timestamp():
    sp = ScenarioPreset(name="test")
    assert sp.id != ""
    assert len(sp.id) == 12
    assert sp.created_at != ""


def test_scenario_preset_round_trip():
    sp = ScenarioPreset(name="parked", context=DrivingContext(scenario="parked"))
    d = sp.model_dump()
    sp2 = ScenarioPreset(**d)
    assert sp2.name == "parked"
    assert sp2.context.scenario == "parked"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_context_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.context'`

- [ ] **Step 3: 实现数据模型**

创建 `app/schemas/` 目录和 `__init__.py`（若不存在），然后创建 `app/schemas/context.py`：

```python
"""驾驶上下文数据模型定义."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class DriverState(BaseModel):
    emotion: Literal["neutral", "anxious", "fatigued", "calm", "angry"] = "neutral"
    workload: Literal["low", "normal", "high", "overloaded"] = "normal"
    fatigue_level: float = Field(default=0.0, ge=0.0, le=1.0)


class GeoLocation(BaseModel):
    latitude: float = Field(default=0.0, ge=-90.0, le=90.0)
    longitude: float = Field(default=0.0, ge=-180.0, le=180.0)
    address: str = ""
    speed_kmh: float = Field(default=0.0, ge=0.0)


class SpatioTemporalContext(BaseModel):
    current_location: GeoLocation = Field(default_factory=GeoLocation)
    destination: GeoLocation | None = None
    eta_minutes: float | None = None
    heading: float | None = Field(default=None, ge=0, le=360)


class TrafficCondition(BaseModel):
    congestion_level: Literal["smooth", "slow", "congested", "blocked"] = "smooth"
    incidents: list[str] = Field(default_factory=list)
    estimated_delay_minutes: int = Field(default=0, ge=0)


class DrivingContext(BaseModel):
    driver: DriverState = Field(default_factory=DriverState)
    spatial: SpatioTemporalContext = Field(default_factory=SpatioTemporalContext)
    traffic: TrafficCondition = Field(default_factory=TrafficCondition)
    scenario: Literal["parked", "city_driving", "highway", "traffic_jam"] = "parked"


class ScenarioPreset(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    context: DrivingContext = Field(default_factory=DrivingContext)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_context_schemas.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add app/schemas/__init__.py app/schemas/context.py tests/test_context_schemas.py
git commit -m "feat: add driving context data models"
```

---

### Task 2: 轻量规则引擎

**Files:**
- Create: `app/agents/rules.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rules.py
"""规则引擎测试."""

from app.agents.rules import Rule, apply_rules, SAFETY_RULES


def test_rule_dataclass():
    r = Rule(
        name="test",
        condition=lambda ctx: True,
        constraint={"allowed_channels": ["audio"]},
        priority=10,
    )
    assert r.name == "test"
    assert r.priority == 10


def test_no_matching_rules():
    ctx = {"scenario": "parked", "driver": {"fatigue_level": 0.1, "workload": "low"}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["visual", "audio", "detailed"]
    assert result["only_urgent"] is False
    assert result["postpone"] is False


def test_highway_rule():
    ctx = {"scenario": "highway", "driver": {"fatigue_level": 0.1, "workload": "low"}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["allowed_channels"] == ["audio"]
    assert result["postpone"] is False


def test_fatigue_rule():
    ctx = {"scenario": "city_driving", "driver": {"fatigue_level": 0.8, "workload": "normal"}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["only_urgent"] is True
    assert result["allowed_channels"] == ["audio"]


def test_overloaded_rule():
    ctx = {"scenario": "city_driving", "driver": {"fatigue_level": 0.3, "workload": "overloaded"}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["postpone"] is True


def test_highway_and_fatigue_intersection():
    """高速+疲劳 → allowed_channels 取交集."""
    ctx = {"scenario": "highway", "driver": {"fatigue_level": 0.8, "workload": "normal"}}
    result = apply_rules(ctx, SAFETY_RULES)
    assert result["only_urgent"] is True
    assert set(result["allowed_channels"]) == {"audio"}


def test_max_frequency_minutes_takes_min():
    """多条规则定义 max_frequency_minutes 时取最小值."""
    rules = [
        Rule(name="r1", condition=lambda c: True, constraint={"max_frequency_minutes": 30}, priority=10),
        Rule(name="r2", condition=lambda c: True, constraint={"max_frequency_minutes": 10}, priority=20),
    ]
    result = apply_rules({"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}}, rules)
    assert result["max_frequency_minutes"] == 10


def test_missing_field_not_constraining():
    """规则A有 allowed_channels，规则B只有 postpone → allowed_channels 仅从A."""
    rules = [
        Rule(name="a", condition=lambda c: True, constraint={"allowed_channels": ["audio", "visual"]}, priority=10),
        Rule(name="b", condition=lambda c: True, constraint={"postpone": True}, priority=20),
    ]
    result = apply_rules({"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}}, rules)
    assert result["allowed_channels"] == ["audio", "visual"]
    assert result["postpone"] is True


def test_empty_intersection_fallback():
    """allowed_channels 交集为空时回退到最后一条定义该字段的规则."""
    rules = [
        Rule(name="a", condition=lambda c: True, constraint={"allowed_channels": ["audio"]}, priority=10),
        Rule(name="b", condition=lambda c: True, constraint={"allowed_channels": ["visual"]}, priority=20),
    ]
    result = apply_rules({"scenario": "any", "driver": {"fatigue_level": 0, "workload": "low"}}, rules)
    assert result["allowed_channels"] == ["visual"]


def test_format_constraints():
    ctx = {"scenario": "highway", "driver": {"fatigue_level": 0.8, "workload": "normal"}}
    result = apply_rules(ctx, SAFETY_RULES)
    text = format_constraints(result)
    assert "audio" in text
    assert "紧急" in text


def test_format_empty_constraints():
    from app.agents.rules import format_constraints
    text = format_constraints({"only_urgent": False, "postpone": False, "allowed_channels": ["visual", "audio", "detailed"]})
    assert "audio" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 实现规则引擎**

```python
# app/agents/rules.py
"""轻量规则引擎 — 安全约束规则定义与合并."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Rule:
    name: str
    condition: Callable[[dict], bool]
    constraint: dict[str, Any]
    priority: int = 0


SAFETY_RULES: list[Rule] = [
    Rule(
        name="highway_audio_only",
        condition=lambda ctx: ctx["scenario"] == "highway",
        constraint={"allowed_channels": ["audio"], "max_frequency_minutes": 30},
        priority=10,
    ),
    Rule(
        name="fatigue_suppress",
        condition=lambda ctx: ctx["driver"]["fatigue_level"] > 0.7,
        constraint={"only_urgent": True, "allowed_channels": ["audio"]},
        priority=20,
    ),
    Rule(
        name="overloaded_postpone",
        condition=lambda ctx: ctx["driver"]["workload"] == "overloaded",
        constraint={"postpone": True},
        priority=15,
    ),
    Rule(
        name="parked_all_channels",
        condition=lambda ctx: ctx["scenario"] == "parked",
        constraint={"allowed_channels": ["visual", "audio", "detailed"]},
        priority=5,
    ),
]


def apply_rules(
    driving_context: dict, rules: list[Rule] | None = None
) -> dict[str, Any]:
    matched = [r for r in (rules or SAFETY_RULES) if r.condition(driving_context)]
    matched.sort(key=lambda r: r.priority, reverse=True)

    channels_rules = [r for r in matched if "allowed_channels" in r.constraint]
    if channels_rules:
        channels = set(channels_rules[0].constraint["allowed_channels"])
        for r in channels_rules[1:]:
            channels &= set(r.constraint["allowed_channels"])
        if not channels:
            channels = set(channels_rules[0].constraint["allowed_channels"])
        merged_channels = sorted(channels)
    else:
        merged_channels = ["visual", "audio", "detailed"]

    only_urgent = any(r.constraint.get("only_urgent", False) for r in matched)
    postpone = any(r.constraint.get("postpone", False) for r in matched)

    freq_rules = [r for r in matched if "max_frequency_minutes" in r.constraint]
    max_freq = min(r.constraint["max_frequency_minutes"] for r in freq_rules) if freq_rules else None

    result: dict[str, Any] = {
        "allowed_channels": merged_channels,
        "only_urgent": only_urgent,
        "postpone": postpone,
    }
    if max_freq is not None:
        result["max_frequency_minutes"] = max_freq
    return result


def format_constraints(constraints: dict[str, Any]) -> str:
    lines = ["【安全约束规则】", "你必须遵守以下约束（由系统规则引擎生成，不可违反）："]
    ch = constraints.get("allowed_channels")
    if ch:
        lines.append(f"- 允许的提醒通道: {ch}")
    if constraints.get("only_urgent"):
        lines.append("- 仅允许紧急提醒: true")
    freq = constraints.get("max_frequency_minutes")
    if freq is not None:
        lines.append(f"- 最大提醒频率: {freq}分钟")
    if constraints.get("postpone"):
        lines.append("- 当前状态需要延后提醒")
    lines.append("")
    lines.append("请在以上约束范围内做出决策。")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agents/rules.py tests/test_rules.py
git commit -m "feat: add lightweight rule engine for safety constraints"
```

---

### Task 3: 工作流改造 — AgentState + WorkflowStages + run_with_stages

**Files:**
- Modify: `app/agents/state.py`
- Modify: `app/agents/workflow.py`
- Modify: `tests/test_chat.py`

- [ ] **Step 1: 更新 AgentState**

`app/agents/state.py` 全部内容替换为：

```python
"""Agent状态定义模块."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict


class AgentState(TypedDict):
    messages: list[dict]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    result: Optional[str]
    event_id: Optional[str]
    driving_context: Optional[dict]
    stages: Optional[dict[str, Any]]


@dataclass
class WorkflowStages:
    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
```

- [ ] **Step 2: 更新 tests/test_chat.py**

`test_chat_feeds_workflow_context` 中的 `AgentState` 构造需要新增 `driving_context` 和 `stages` 字段：

```python
    state: AgentState = {
        "messages": [{"role": "user", "content": "查一下会议"}],
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
        "driving_context": None,
        "stages": None,
    }
```

- [ ] **Step 3: 改造 AgentWorkflow**

`app/agents/workflow.py` 主要变更：

1. 删除 `run()` 方法，新增 `run_with_stages()` 
2. `_context_node`: 当 `driving_context` 存在时跳过 LLM，直接构建 context dict
3. `_strategy_node`: 内部前置调用 `apply_rules`，注入约束到 prompt
4. 各 node 通过 `state["stages"]` 收集阶段输出

具体实现：

```python
# workflow.py 关键变更点

from app.agents.state import AgentState, WorkflowStages
from app.agents.rules import apply_rules, format_constraints

# AgentWorkflow.__init__ — 不变

async def _context_node(self, state: AgentState) -> dict:
    messages = state.get("messages", [])
    user_input = "" if not messages else str(messages[-1].get("content", ""))
    stages = state.get("stages")

    driving_context = state.get("driving_context")
    if driving_context:
        try:
            related_events = (
                await self.memory_module.search(user_input, mode=self._memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            related_events = []

        relevant_memories = [e.to_public() for e in related_events] if related_events else []

        context = dict(driving_context)
        context["current_datetime"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        context["related_events"] = [e.model_dump() for e in related_events] if related_events else []
        context["relevant_memories"] = relevant_memories
    else:
        # 原有 LLM 推断路径（完全保留）
        try:
            related_events = (
                await self.memory_module.search(user_input, mode=self._memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            related_events = []

        try:
            if related_events:
                relevant_memories = [e.to_public() for e in related_events]
            else:
                relevant_memories = [
                    e.model_dump()
                    for e in await self.memory_module.get_history(
                        mode=self._memory_mode
                    )
                ]
        except Exception as e:
            logger.warning("Memory get_history failed: %s", e)
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )

        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SYSTEM_PROMPTS["context"].format(
            current_datetime=current_datetime
        )

        prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

        context = await self._call_llm_json(prompt)
        context["related_events"] = [e.model_dump() for e in related_events] if related_events else []
        context["relevant_memories"] = relevant_memories

    if stages is not None:
        stages["context"] = context

    return {
        "context": context,
        "messages": state["messages"]
        + [{"role": "user", "content": f"Context: {json.dumps(context)}"}],
    }

async def _strategy_node(self, state: AgentState) -> dict:
    messages = state.get("messages", [])
    user_input = messages[-1].get("content", "") if messages else ""
    context = state.get("context", {})
    task = state.get("task", {})
    stages = state.get("stages")

    strategies = await self._strategies_store.read()

    constraints_block = ""
    driving_context = state.get("driving_context")
    if driving_context:
        constraints = apply_rules(driving_context)
        constraints_block = "\n\n" + format_constraints(constraints)
        if stages is not None:
            stages["constraints"] = constraints

    prompt = f"""{SYSTEM_PROMPTS["strategy"]}
{constraints_block}
上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}

请输出JSON格式的决策结果. """

    decision = await self._call_llm_json(prompt)

    if stages is not None:
        stages["decision"] = decision

    return {
        "decision": decision,
        "messages": state["messages"]
        + [{"role": "user", "content": f"Decision: {json.dumps(decision)}"}],
    }

async def _task_node(self, state: AgentState) -> dict:
    messages = state.get("messages", [])
    user_input = messages[-1].get("content", "") if messages else ""
    context = state.get("context", {})
    stages = state.get("stages")

    prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象. """

    task = await self._call_llm_json(prompt)

    if stages is not None:
        stages["task"] = task

    return {
        "task": task,
        "messages": state["messages"]
        + [{"role": "user", "content": f"Task: {json.dumps(task)}"}],
    }

async def _execution_node(self, state: AgentState) -> dict:
    decision = state.get("decision") or {}
    messages = state.get("messages", [])
    user_input = str(messages[0].get("content", "")) if messages else ""
    stages = state.get("stages")

    remind_content = decision.get("reminder_content") or decision.get(
        "remind_content"
    )
    if isinstance(remind_content, dict):
        content = remind_content.get("text") or remind_content.get(
            "content", "无提醒内容"
        )
    elif isinstance(remind_content, str):
        content = remind_content
    else:
        content = decision.get("content") or "无提醒内容"
    event_id = await self.memory_module.write_interaction(
        user_input, content, mode=self._memory_mode
    )
    if not event_id:
        logger.warning("Memory write returned empty event_id, using fallback")
        event_id = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"

    result = f"提醒已发送: {content}"

    if stages is not None:
        stages["execution"] = {"content": content, "event_id": event_id, "result": result}

    return {
        "result": result,
        "event_id": event_id,
        "messages": state["messages"] + [{"role": "user", "content": result}],
    }

async def run_with_stages(
    self,
    user_input: str,
    driving_context: dict | None = None,
) -> tuple[str, str | None, WorkflowStages]:
    """运行完整工作流并返回结果、事件ID和各阶段输出."""
    stages = WorkflowStages()
    state: AgentState = {
        "messages": [{"role": "user", "content": user_input}],
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
        "driving_context": driving_context,
        "stages": stages.__dict__,
    }

    for node_fn in self._nodes:
        updates = await node_fn(state)
        state.update(updates)

    result = state.get("result") or "处理完成"
    event_id = state.get("event_id")
    return result, event_id, stages
```

注意：删除 `create_workflow()` 和旧 `run()` 方法。

- [ ] **Step 4: 搜索所有调用旧 `run()` 的地方并更新**

Run: `grep -rn "\.run(" app/ tests/ --include="*.py"`
逐一更新为 `run_with_stages()`。主要在：
- `app/api/main.py`（将在 Task 4 中重写，此处只需确保工作流测试通过）

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_chat.py tests/test_context_schemas.py tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 6: Lint + Typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/agents/state.py app/agents/workflow.py tests/test_chat.py
git commit -m "feat: extend AgentState, add run_with_stages, inject context into workflow"
```

---

### Task 4: GraphQL Schema + Resolvers + 删除 REST API

**Files:**
- Create: `app/api/graphql_schema.py`
- Create: `app/api/resolvers/__init__.py`
- Create: `app/api/resolvers/query.py`
- Create: `app/api/resolvers/mutation.py`
- Rewrite: `app/api/main.py`
- Test: `tests/test_graphql.py`
- Delete: `tests/test_api.py`

- [ ] **Step 1: 安装 strawberry-graphql 依赖**

Run: `uv add "strawberry-graphql[fastapi]>=0.260.0"`

- [ ] **Step 2: 写失败测试**

```python
# tests/test_graphql.py
"""GraphQL 端点测试."""

import pytest
from fastapi.testclient import TestClient

from app.schemas.context import DrivingContext


@pytest.fixture
def client() -> TestClient:
    from app.api.main import app
    return TestClient(app)


GRAPHQL_ENDPOINT = "/graphql"


def _graphql_query(client: TestClient, query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = client.post(GRAPHQL_ENDPOINT, json=payload)
    return resp.json()


def test_graphql_playground_redirect(client: TestClient) -> None:
    resp = client.get("/graphql", follow_redirects=False)
    assert resp.status_code in (200, 307, 308)


def test_health_check_query(client: TestClient) -> None:
    result = _graphql_query(client, "{ __typename }")
    assert "data" in result


def test_experiment_report_query(client: TestClient) -> None:
    result = _graphql_query(client, "{ experimentReport { report } }")
    assert "data" in result
    assert result["data"]["experimentReport"]["report"] is not None


def test_scenario_presets_query(client: TestClient) -> None:
    result = _graphql_query(client, "{ scenarioPresets { id name } }")
    assert "data" in result
    assert isinstance(result["data"]["scenarioPresets"], list)


def test_save_scenario_preset(client: TestClient) -> None:
    result = _graphql_query(client, """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) {
                id name
            }
        }
    """, {"name": "test-highway", "ctx": {"scenario": "highway"}})
    assert "data" in result
    preset = result["data"]["saveScenarioPreset"]
    assert preset["name"] == "test-highway"
    assert preset["id"] != ""


def test_delete_scenario_preset(client: TestClient) -> None:
    result = _graphql_query(client, """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) { id }
        }
    """, {"name": "to-delete", "ctx": {"scenario": "parked"}})
    preset_id = result["data"]["saveScenarioPreset"]["id"]

    del_result = _graphql_query(client, """
        mutation($id: String!) { deleteScenarioPreset(id: $id) }
    """, {"id": preset_id})
    assert del_result["data"]["deleteScenarioPreset"] is True


def test_delete_nonexistent_preset(client: TestClient) -> None:
    result = _graphql_query(client, """
        mutation { deleteScenarioPreset(id: "nonexistent") }
    """)
    assert result["data"]["deleteScenarioPreset"] is False


def test_feedback_invalid_action(client: TestClient) -> None:
    result = _graphql_query(client, """
        mutation {
            submitFeedback(input: { eventId: "x", action: "invalid" }) {
                status
            }
        }
    """)
    assert "errors" in result


def test_history_query(client: TestClient) -> None:
    result = _graphql_query(client, """
        query { history(limit: 5, memoryMode: MEMORY_BANK) { id content } }
    """)
    assert "data" in result
    assert isinstance(result["data"]["history"], list)


@pytest.mark.integration
def test_process_query_without_context(
    client: TestClient, llm_provider, tmp_path, monkeypatch
) -> None:
    """验证无上下文注入时的 processQuery（走 LLM 路径）."""
    from app.models.settings import LLMProviderConfig
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    from app.models.chat import ChatModel
    ChatModel(providers=[llm_provider])

    from app.storage.toml_store import _LIST_WRAPPER_KEY
    import tomli_w
    (tmp_path / "events.toml").write_bytes(
        tomli_w.dumps({_LIST_WRAPPER_KEY: []})
    )
    (tmp_path / "strategies.toml").write_bytes(
        tomli_w.dumps({"reminder_weights": {}})
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # 需要重建 MemoryModule 单例
    import app.api.main as api_main
    api_main._memory_module = None

    result = _graphql_query(client, """
        mutation {
            processQuery(input: {
                query: "测试查询"
                memoryMode: MEMORY_BANK
            }) {
                result eventId
            }
        }
    """)
    assert "data" in result
    assert result["data"]["processQuery"]["result"] is not None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_graphql.py -v -k "not integration"`
Expected: FAIL（graphql endpoint 不存在）

- [ ] **Step 4: 实现 GraphQL Schema + Resolvers**

`app/api/graphql_schema.py`:

```python
"""Strawberry GraphQL Schema 定义."""

from __future__ import annotations

from typing import Any, NewType, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON as StrawberryJSON

from app.schemas.context import (
    DriverState,
    DrivingContext,
    GeoLocation,
    ScenarioPreset,
    SpatioTemporalContext,
    TrafficCondition,
)
from app.memory.types import MemoryMode

JSON = strawberry.scalar(
    NewType("JSON", object),
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


@strawberry.enum
class MemoryModeEnum:
    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"


@strawberry.input
class GeoLocationInput:
    latitude: float
    longitude: float
    address: str = ""
    speed_kmh: float = 0.0


@strawberry.input
class DriverStateInput:
    emotion: str = "neutral"
    workload: str = "normal"
    fatigue_level: float = 0.0


@strawberry.input
class SpatioTemporalContextInput:
    current_location: GeoLocationInput
    destination: Optional[GeoLocationInput] = None
    eta_minutes: Optional[float] = None
    heading: Optional[float] = None


@strawberry.input
class TrafficConditionInput:
    congestion_level: str = "smooth"
    incidents: list[str] = strawberry.field(default_factory=list)
    estimated_delay_minutes: int = 0


@strawberry.input
class DrivingContextInput:
    driver: Optional[DriverStateInput] = None
    spatial: Optional[SpatioTemporalContextInput] = None
    traffic: Optional[TrafficConditionInput] = None
    scenario: str = "parked"


@strawberry.input
class ProcessQueryInput:
    query: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    context: Optional[DrivingContextInput] = None


@strawberry.input
class FeedbackInput:
    event_id: str
    action: str
    modified_content: Optional[str] = None


@strawberry.input
class ScenarioPresetInput:
    name: str
    context: DrivingContextInput


@strawberry.type
class GeoLocationGQL:
    latitude: float
    longitude: float
    address: str
    speed_kmh: float


@strawberry.type
class DriverStateGQL:
    emotion: str
    workload: str
    fatigue_level: float


@strawberry.type
class SpatioTemporalContextGQL:
    current_location: GeoLocationGQL
    destination: Optional[GeoLocationGQL]
    eta_minutes: Optional[float]
    heading: Optional[float]


@strawberry.type
class TrafficConditionGQL:
    congestion_level: str
    incidents: list[str]
    estimated_delay_minutes: int


@strawberry.type
class DrivingContextGQL:
    driver: DriverStateGQL
    spatial: SpatioTemporalContextGQL
    traffic: TrafficConditionGQL
    scenario: str


@strawberry.type
class WorkflowStagesGQL:
    context: JSON
    task: JSON
    decision: JSON
    execution: JSON


@strawberry.type
class ProcessQueryResult:
    result: str
    event_id: Optional[str]
    stages: Optional[WorkflowStagesGQL]


@strawberry.type
class MemoryEventGQL:
    id: str
    content: str
    type: str
    description: str
    created_at: str


@strawberry.type
class ExperimentReport:
    report: str


@strawberry.type
class ScenarioPresetGQL:
    id: str
    name: str
    context: DrivingContextGQL
    created_at: str


@strawberry.type
class FeedbackResult:
    status: str
```

`app/api/resolvers/query.py`:

```python
"""Query resolvers."""

from __future__ import annotations

from typing import Optional

import strawberry

from app.api.graphql_schema import (
    ExperimentReport,
    MemoryEventGQL,
    MemoryModeEnum,
    ScenarioPresetGQL,
)
from app.memory.types import MemoryMode


@strawberry.type
class Query:
    @strawberry.field
    async def history(
        self, limit: int = 10, memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    ) -> list[MemoryEventGQL]:
        from app.api.main import get_memory_module

        mm = get_memory_module()
        mode = MemoryMode(memory_mode.value)
        events = await mm.get_history(limit=limit)
        return [
            MemoryEventGQL(
                id=e.id,
                content=e.content,
                type=e.type,
                description=e.description,
                created_at=e.created_at,
            )
            for e in events
        ]

    @strawberry.field
    def experiment_report(self) -> ExperimentReport:
        return ExperimentReport(report="Experiment runner migrated to CLI pipeline")

    @strawberry.field
    async def scenario_presets(self) -> list[ScenarioPresetGQL]:
        from app.api.resolvers.mutation import _preset_store, _to_gql_preset

        store = _preset_store()
        presets = await store.read()
        return [_to_gql_preset(p) for p in presets]
```

`app/api/resolvers/mutation.py`:

```python
"""Mutation resolvers."""

from __future__ import annotations

from pathlib import Path

import strawberry
from strawberry import GraphQLError

from app.api.graphql_schema import (
    DrivingContextGQL,
    DrivingStateGQL,
    GeoLocationGQL,
    FeedbackInput,
    FeedbackResult,
    MemoryModeEnum,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
    WorkflowStagesGQL,
)
from app.memory.schemas import FeedbackData
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore


def _preset_store() -> TOMLStore:
    from app.api.main import DATA_DIR
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def _input_to_context_dict(input_obj) -> dict:
    result: dict = {
        "scenario": input_obj.scenario,
        "driver": {},
        "spatial": {},
        "traffic": {},
    }
    if input_obj.driver:
        result["driver"] = {
            "emotion": input_obj.driver.emotion,
            "workload": input_obj.driver.workload,
            "fatigue_level": input_obj.driver.fatigue_level,
        }
    if input_obj.spatial:
        result["spatial"] = {
            "current_location": {
                "latitude": input_obj.spatial.current_location.latitude,
                "longitude": input_obj.spatial.current_location.longitude,
                "address": input_obj.spatial.current_location.address,
                "speed_kmh": input_obj.spatial.current_location.speed_kmh,
            },
        }
        if input_obj.spatial.destination:
            result["spatial"]["destination"] = {
                "latitude": input_obj.spatial.destination.latitude,
                "longitude": input_obj.spatial.destination.longitude,
                "address": input_obj.spatial.destination.address,
                "speed_kmh": input_obj.spatial.destination.speed_kmh,
            }
        if input_obj.spatial.eta_minutes is not None:
            result["spatial"]["eta_minutes"] = input_obj.spatial.eta_minutes
        if input_obj.spatial.heading is not None:
            result["spatial"]["heading"] = input_obj.spatial.heading
    if input_obj.traffic:
        result["traffic"] = {
            "congestion_level": input_obj.traffic.congestion_level,
            "incidents": input_obj.traffic.incidents,
            "estimated_delay_minutes": input_obj.traffic.estimated_delay_minutes,
        }
    return result


def _dict_to_gql_context(d: dict) -> DrivingContextGQL:
    driver_d = d.get("driver", {})
    spatial_d = d.get("spatial", {})
    traffic_d = d.get("traffic", {})
    loc = spatial_d.get("current_location", {})
    dest = spatial_d.get("destination")
    return DrivingContextGQL(
        driver=DriverStateGQL(
            emotion=driver_d.get("emotion", "neutral"),
            workload=driver_d.get("workload", "normal"),
            fatigue_level=driver_d.get("fatigue_level", 0.0),
        ),
        spatial=SpatioTemporalContextGQL(
            current_location=GeoLocationGQL(
                latitude=loc.get("latitude", 0.0),
                longitude=loc.get("longitude", 0.0),
                address=loc.get("address", ""),
                speed_kmh=loc.get("speed_kmh", 0.0),
            ),
            destination=GeoLocationGQL(
                latitude=dest["latitude"],
                longitude=dest["longitude"],
                address=dest.get("address", ""),
                speed_kmh=dest.get("speed_kmh", 0.0),
            )
            if dest
            else None,
            eta_minutes=spatial_d.get("eta_minutes"),
            heading=spatial_d.get("heading"),
        ),
        traffic=TrafficConditionGQL(
            congestion_level=traffic_d.get("congestion_level", "smooth"),
            incidents=traffic_d.get("incidents", []),
            estimated_delay_minutes=traffic_d.get("estimated_delay_minutes", 0),
        ),
        scenario=d.get("scenario", "parked"),
    )


def _to_gql_preset(p: dict) -> ScenarioPresetGQL:
    from app.schemas.context import DrivingContext as DCM
    ctx = DCM(**{k: v for k, v in p.get("context", {}).items() if k in DCM.model_fields})
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=_dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def process_query(self, input: ProcessQueryInput) -> ProcessQueryResult:
        from app.api.main import get_memory_module
        from app.agents.workflow import AgentWorkflow

        try:
            mm = get_memory_module()
            workflow = AgentWorkflow(
                data_dir=getattr(get_memory_module, '_data_dir', Path("data")),
                memory_mode=MemoryMode(input.memory_mode.value),
                memory_module=mm,
            )

            driving_context = None
            if input.context:
                driving_context = _input_to_context_dict(input.context)

            result, event_id, stages = await workflow.run_with_stages(
                input.query, driving_context
            )
            return ProcessQueryResult(
                result=result,
                event_id=event_id,
                stages=WorkflowStagesGQL(
                    context=stages.context,
                    task=stages.task,
                    decision=stages.decision,
                    execution=stages.execution,
                ),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("processQuery failed: %s", e)
            raise GraphQLError(f"Internal server error: {e}")

    @strawberry.mutation
    async def submit_feedback(self, input: FeedbackInput) -> FeedbackResult:
        if input.action not in ("accept", "ignore"):
            raise GraphQLError(f"Invalid action: {input.action!r}. Must be 'accept' or 'ignore'")
        from app.api.main import get_memory_module

        try:
            mm = get_memory_module()
            feedback = FeedbackData(
                action=input.action,
                modified_content=input.modified_content,
            )
            await mm.update_feedback(input.event_id, feedback)
            return FeedbackResult(status="success")
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("submitFeedback failed: %s", e)
            raise GraphQLError(f"Internal server error: {e}")

    @strawberry.mutation
    async def save_scenario_preset(self, input: ScenarioPresetInput) -> ScenarioPresetGQL:
        from app.schemas.context import ScenarioPreset

        store = _preset_store()
        preset = ScenarioPreset(name=input.name)
        if input.context:
            preset.context = ScenarioPreset.model_fields["context"].default
            ctx_dict = _input_to_context_dict(input.context)
            for key in ["driver", "spatial", "traffic"]:
                if key in ctx_dict:
                    setattr(preset.context, key, type(getattr(preset.context, key))(**ctx_dict[key]))
            preset.context.scenario = ctx_dict.get("scenario", "parked")
        await store.append(preset.model_dump())
        return _to_gql_preset(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(self, id: str) -> bool:
        store = _preset_store()
        presets = await store.read()
        new_presets = [p for p in presets if p.get("id") != id]
        if len(new_presets) == len(presets):
            return False
        await store.write(new_presets)
        return True
```

- [ ] **Step 5: 重写 app/api/main.py**

```python
"""FastAPI 应用主入口."""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path
import os
import logging

from app.api.graphql_schema import Query, Mutation
from app.memory.memory import MemoryModule

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="知行车秘 - 车载AI智能体")

_data_dir_env = os.getenv("DATA_DIR", "data")
DATA_DIR = Path(_data_dir_env)


def _ensure_memory_module() -> MemoryModule:
    from app.models.settings import get_chat_model, get_embedding_model
    return MemoryModule(
        data_dir=DATA_DIR, embedding_model=get_embedding_model(), chat_model=get_chat_model()
    )


_memory_module: MemoryModule | None = None


def get_memory_module() -> MemoryModule:
    global _memory_module
    if _memory_module is None:
        _memory_module = _ensure_memory_module()
    return _memory_module


import strawberry

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = strawberry.fastapi.GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

webui_path = Path(__file__).parent.parent.parent / "webui"


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(webui_path / "index.html")
```

注意：`main.py`（项目入口）中的 `root()` 路由定义需要删除（已在 `app/api/main.py` 中定义）。

- [ ] **Step 6: 删除旧 REST API 测试**

Run: `rm tests/test_api.py`

- [ ] **Step 7: 更新 main.py 项目入口**

`main.py` 删除 `root()` 路由（已在 `app/api/main.py` 中定义），简化为：

```python
"""记忆工作台主入口."""

import os
import uvicorn
from pathlib import Path
from app.api.main import app
from app.storage.init_data import init_storage

if __name__ == "__main__":
    init_storage(Path(os.getenv("DATA_DIR", "data")))
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 8: 运行测试确认通过**

Run: `uv run pytest tests/test_graphql.py -v -k "not integration"`
Expected: PASS

- [ ] **Step 9: Lint + Typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`
Expected: PASS（修复所有问题）

- [ ] **Step 10: Commit**

```bash
git add app/api/ tests/test_graphql.py main.py
git rm tests/test_api.py
git commit -m "feat: replace REST API with GraphQL (Strawberry)"
```

---

### Task 5: init_data 更新

**Files:**
- Modify: `app/storage/init_data.py`

- [ ] **Step 1: 在 `list_files` dict 中新增 `scenario_presets.toml`**

```python
    list_files = {
        "events.toml": [],
        "interactions.toml": [],
        "feedback.toml": [],
        "experiment_results.toml": [],
        "scenario_presets.toml": [],
    }
```

- [ ] **Step 2: 运行测试确认无回归**

Run: `uv run pytest tests/ -v -k "not integration"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/storage/init_data.py
git commit -m "feat: add scenario_presets.toml to storage initialization"
```

---

### Task 6: 模拟测试 WebUI

**Files:**
- Rewrite: `webui/index.html`

- [ ] **Step 1: 重写 webui/index.html**

纯 HTML/CSS/JS 单页应用，基于 GraphQL API：

- 左侧场景配置面板（驾驶员状态、时空信息、交通状况、场景选择、预设管理）
- 右侧工作流调试面板（输入、四阶段输出、历史记录）
- 底部 GraphQL Playground 入口链接
- 使用 `fetch` 调用 `/graphql`

（页面内容较长，实施时直接编写完整 HTML 文件，包含：
1. 场景预设下拉 → 自动填充面板
2. 各字段输入控件（下拉、滑块、输入框）
3. 保存预设按钮
4. 查询输入 + 发送按钮
5. 四阶段 JSON 折叠面板（Context/Task/Strategy/Execution）
6. 接受/忽略反馈按钮
7. 历史记录列表
8. GraphQL Playground 链接）

- [ ] **Step 2: 手动验证页面可访问**

Run: `uv run python main.py`
访问 http://localhost:8000 确认页面加载正常

- [ ] **Step 3: Commit**

```bash
git add webui/index.html
git commit -m "feat: rewrite WebUI as simulation test workbench"
```

---

### Task 7: 全量测试 + Lint + Typecheck

**Files:**
- All

- [ ] **Step 1: 运行全量测试**

Run: `uv run pytest tests/ -v -k "not integration"`
Expected: ALL PASS

- [ ] **Step 2: Lint + Typecheck**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`
Expected: PASS

- [ ] **Step 3: 最终 Commit（如有修复）**

```bash
git add -A
git commit -m "chore: fix lint and type issues"
```
