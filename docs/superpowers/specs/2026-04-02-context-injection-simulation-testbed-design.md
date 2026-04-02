# 上下文注入与模拟测试工作台设计

## 背景

开题报告提出四层架构（情境建模层 → 任务理解层 → 策略决策层 → 执行与反馈层），当前实现中情境建模层完全依赖 LLM 编造上下文，缺乏真实外部数据注入。本设计补齐该缺口，并提供模拟测试页面用于场景验证。

## 核心决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据注入方式 | 请求级上下文注入 | 无状态、易测试、外部对接自然 |
| API 风格 | GraphQL（Strawberry + FastAPI）与 REST 共存 | GraphQL 处理新功能，REST 保留向后兼容 |
| 策略决策 | 轻量规则 + LLM | 关键安全约束走规则，其余 LLM 生成 |
| 时空数据粒度 | 细粒度（坐标级） | 支持精确场景模拟 |
| WebUI 定位 | 场景模拟 + 工作流调试 | 可视化各 Agent 阶段输出 |

## 1. 数据模型

新增 `app/schemas/context.py`，定义外部上下文数据结构。枚举字段使用 `Literal` 约束合法值。

```python
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
    current_location: GeoLocation = GeoLocation()
    destination: GeoLocation | None = None
    eta_minutes: float | None = None
    heading: float | None = Field(default=None, ge=0, le=360)

class TrafficCondition(BaseModel):
    congestion_level: Literal["smooth", "slow", "congested", "blocked"] = "smooth"
    incidents: list[str] = []
    estimated_delay_minutes: int = Field(default=0, ge=0)

class DrivingContext(BaseModel):
    driver: DriverState = DriverState()
    spatial: SpatioTemporalContext = SpatioTemporalContext()
    traffic: TrafficCondition = TrafficCondition()
    scenario: Literal["parked", "city_driving", "highway", "traffic_jam"] = "parked"
```

`DrivingContext` 可选 — 不传时走原有纯 LLM 推断路径，向后兼容。

### 场景预设数据模型

```python
import uuid
from datetime import datetime, timezone

class ScenarioPreset(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    context: DrivingContext = DrivingContext()
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

存储于 `data/scenario_presets.toml`，结构为 `list[ScenarioPreset]`。所有时间戳统一为 ISO 8601 UTC 格式。

## 2. GraphQL API 层

使用 Strawberry GraphQL 库与 FastAPI 集成，与现有 REST API 共存。

### 2.1 技术选型

- **Strawberry**：code-first GraphQL 库，原生支持 Pydantic 模型转换，与 FastAPI 无缝集成
- 依赖：`strawberry-graphql[fastapi]`

### 2.2 Schema 定义

```graphql
enum MemoryMode {
  MEMORY_BANK
  MEMOCHAT
}

scalar JSON

type Query {
  history(limit: Int = 10, memoryMode: MemoryMode! = MEMORY_BANK): [MemoryEventGQL!]!
  experimentReport: ExperimentReport!
  scenarioPresets: [ScenarioPreset!]!
}

type Mutation {
  processQuery(input: ProcessQueryInput!): ProcessQueryResult!
  submitFeedback(input: FeedbackInput!): FeedbackResult!
  saveScenarioPreset(input: ScenarioPresetInput!): ScenarioPreset!
  deleteScenarioPreset(id: String!): Boolean!
}

input ProcessQueryInput {
  query: String!
  memoryMode: MemoryMode! = MEMORY_BANK
  context: DrivingContextInput
}

input DrivingContextInput {
  driver: DriverStateInput
  spatial: SpatioTemporalContextInput
  traffic: TrafficConditionInput
  scenario: String = "parked"
}

input DriverStateInput {
  emotion: String! = "neutral"
  workload: String! = "normal"
  fatigueLevel: Float! = 0.0
}

input SpatioTemporalContextInput {
  currentLocation: GeoLocationInput!
  destination: GeoLocationInput
  etaMinutes: Float
  heading: Float
}

input GeoLocationInput {
  latitude: Float!
  longitude: Float!
  address: String! = ""
  speedKmh: Float! = 0.0
}

input TrafficConditionInput {
  congestionLevel: String! = "smooth"
  incidents: [String!]! = []
  estimatedDelayMinutes: Int! = 0
}

type ProcessQueryResult {
  result: String!
  eventId: String
  stages: WorkflowStages
}

type WorkflowStages {
  context: JSON!
  task: JSON!
  decision: JSON!
  execution: JSON!
}

type MemoryEventGQL {
  id: String!
  content: String!
  type: String!
  description: String!
  createdAt: String!
}

type ExperimentReport {
  report: String!
}

type ScenarioPreset {
  id: String!
  name: String!
  context: DrivingContextGQL!
  createdAt: String!
}

type DrivingContextGQL {
  driver: DriverStateGQL!
  spatial: SpatioTemporalContextGQL!
  traffic: TrafficConditionGQL!
  scenario: String!
}

type DriverStateGQL {
  emotion: String!
  workload: String!
  fatigueLevel: Float!
}

type SpatioTemporalContextGQL {
  currentLocation: GeoLocationGQL!
  destination: GeoLocationGQL
  etaMinutes: Float
  heading: Float
}

type GeoLocationGQL {
  latitude: Float!
  longitude: Float!
  address: String!
  speedKmh: Float!
}

type TrafficConditionGQL {
  congestionLevel: String!
  incidents: [String!]!
  estimatedDelayMinutes: Int!
}

input FeedbackInput {
  eventId: String!
  action: String!
  modifiedContent: String
}

type FeedbackResult {
  status: String!
}

input ScenarioPresetInput {
  name: String!
  context: DrivingContextInput!
}
```

### 2.3 与现有 REST API 的关系

- **共存方案**：GraphQL 端点挂载在 `/graphql`，原有 REST 端点全部保留
- GraphQL playground 自动可用（Strawberry 提供），便于开发调试
- 新功能（上下文注入、场景预设、工作流调试）仅通过 GraphQL 暴露
- REST 端点的 `AgentWorkflow.run()` 调用不变（不传 `driving_context`，返回值保持二元素）

### 2.4 GraphQL 错误处理

- 业务异常（查询失败、反馈失败等）转换为 GraphQL `GraphQLError`，在 `errors` 数组中返回
- 使用 Strawberry 的 `raise GraphQLError("message")` 模式
- HTTP 层面的错误（如 404）仍由 FastAPI 处理

### 2.5 Strawberry 实现注意事项

- **JSON scalar**：通过 `strawberry.scalar(NewType("JSON", object), serialize=lambda v: v, parse_value=lambda v: v)` 定义
- **FeedbackInput.action**：在 resolver 中校验 `action in ("accept", "ignore")`，不合法时 raise `GraphQLError("Invalid action")`
- **deleteScenarioPreset**：删除不存在的 ID 返回 `false`，不抛异常

### 2.6 文件结构

```
app/api/
├── main.py              # FastAPI app，挂载 GraphQL router，保留 REST 端点
├── graphql_schema.py    # Strawberry schema 定义（type/mutation/query）
├── resolvers/
│   ├── __init__.py
│   ├── query.py         # Query resolvers
│   └── mutation.py      # Mutation resolvers
```

## 3. 工作流改造

### 3.1 AgentState 扩展

`app/agents/state.py` 的 `AgentState` TypedDict 新增字段：

```python
class AgentState(TypedDict):
    messages: list[dict]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    result: Optional[str]
    event_id: Optional[str]
    driving_context: Optional[dict]  # 新增：外部注入的驾驶上下文
```

### 3.2 AgentWorkflow 签名

保持 `run()` 返回二元素（向后兼容 REST），新增 `run_with_stages()` 方法：

```python
async def run(self, user_input: str, driving_context: dict | None = None) -> tuple[str, str | None]:
    """运行工作流，返回 (result, event_id)。向后兼容。"""
    result, event_id, _ = await self.run_with_stages(user_input, driving_context)
    return result, event_id

async def run_with_stages(
    self, user_input: str, driving_context: dict | None = None
) -> tuple[str, str | None, WorkflowStages]:
    """运行工作流，返回 (result, event_id, stages)。"""
```

### 3.3 Context Node 使用真实数据

当 `state["driving_context"]` 非空时：
- 跳过 LLM 调用，直接将 `driving_context` 作为 context 基础
- 附加 `current_datetime`（ISO 8601 格式）
- 执行 memory 搜索，将结果附加到 `related_events` 和 `relevant_memories` 字段（保持与 LLM 路径一致的输出结构）
- 最终输出结构：`{"driver": ..., "spatial": ..., "traffic": ..., "scenario": ..., "current_datetime": "...", "related_events": [...], "relevant_memories": [...]}`

当 `state["driving_context"]` 为空时：
- 走原有 LLM 推断路径（向后兼容）

### 3.4 各阶段输出收集

新增 `WorkflowStages` 数据类，工作流执行过程中逐步填充：

```python
@dataclass
class WorkflowStages:
    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
```

`run_with_stages()` 内部创建 `WorkflowStages` 实例，每个 node 执行后将输出写入对应字段。通过闭包方式：`run_with_stages()` 内部创建 `stages`，node 函数通过闭包捕获并写入。`stages` 实例挂载到 `state["stages"]` 供各 node 访问。

## 4. 轻量规则引擎

在 Strategy Agent 之前，基于 `DrivingContext` 应用安全约束规则。

### 4.1 Rule 数据类

```python
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class Rule:
    name: str
    condition: Callable[[dict], bool]  # 接收 DrivingContext 的 dict 表示
    constraint: dict[str, Any]         # 约束内容
    priority: int = 0                  # 数字越大优先级越高
```

### 4.2 规则定义

```python
# app/agents/rules.py

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
```

### 4.3 规则合并策略

多规则同时匹配时，按优先级从高到低处理。**仅对该字段存在于 constraint 中的规则参与合并**，缺失该字段的规则视为"不约束"：
- `allowed_channels`：仅对定义了该字段的规则取交集（最严格约束）。若交集为空，取最后一条定义该字段的规则的值
- `only_urgent`：任一定义了该字段且为 True 的规则生效
- `postpone`：任一定义了该字段且为 True 的规则生效
- `max_frequency_minutes`：仅对定义了该字段的规则取最小值（分钟整数）

### 4.4 规则引擎输出格式

规则引擎输出合并后的 `constraints` 字典，序列化为 JSON 注入 Strategy prompt：

```
【安全约束规则】
你必须遵守以下约束（由系统规则引擎生成，不可违反）：
- 允许的提醒通道: ["audio"]
- 仅允许紧急提醒: true
- 最大提醒频率: 30分钟

请在以上约束范围内做出决策。
```

### 4.5 应用时机

```
Context Node → Task Node → [Rule Engine] → Strategy Node → Execution Node
```

规则引擎在 Task Node 之后、Strategy Node 之前执行。仅当 `driving_context` 存在时执行；否则跳过，Strategy Agent 自行决策。

实现方式：`_strategy_node` 方法内部前置调用规则引擎（`_apply_rules`），根据 `state["driving_context"]` 是否存在决定是否注入约束。不新增独立的 node 方法，避免修改 `_nodes` 静态列表的顺序逻辑。

### 4.6 postpone 处理

P0 阶段：postpone 规则匹配时，Strategy Node 返回 `{"should_remind": false, "reason": "postponed", "postpone_reason": "overloaded"}`，由调用方（前端/外部系统）决定何时重试。不引入异步状态机。

### 4.7 Strategy prompt 更新

当规则引擎产出约束时，Strategy prompt 变为：

```
{STRATEGY_SYSTEM_PROMPT}

{constraints_block}

上下文: {context}
任务: {task}
个性化策略: {strategies}

请输出JSON格式的决策结果.
```

`constraints_block` 为 4.4 节描述的格式。无约束时 `constraints_block` 为空字符串。

## 5. 模拟测试 WebUI

### 5.1 页面布局

```
┌──────────────────────────────────────────────────┐
│  知行车秘 — 模拟测试工作台                          │
├──────────────┬───────────────────────────────────┤
│  场景配置面板  │  工作流调试面板                      │
│              │                                   │
│ [场景预设下拉] │  用户输入: [____________] [发送]     │
│              │                                   │
│ ─ 驾驶员状态 ─ │  ┌─ Context Agent ──────────────┐ │
│ 情绪: [下拉]  │  │ { JSON 输出 }                │ │
│ 负荷: [下拉]  │  └──────────────────────────────┘ │
│ 疲劳: [滑块]  │  ┌─ Task Agent ────────────────┐  │
│              │  │ { JSON 输出 }                │  │
│ ─ 时空信息 ── │  └──────────────────────────────┘ │
│ 纬度: [输入]  │  ┌─ Strategy Agent ────────────┐  │
│ 经度: [输入]  │  │ { JSON 输出 }                │  │
│ 地址: [输入]  │  └──────────────────────────────┘ │
│ 车速: [输入]  │  ┌─ Execution Agent ───────────┐  │
│ 目的地: [...]  │  │ 提醒已发送: ...              │  │
│ ETA: [输入]   │  │ [接受] [忽略]                │  │
│              │  └──────────────────────────────┘ │
│ ─ 交通状况 ── │                                   │
│ 拥堵: [下拉]  │  ── 历史记录 ───────────────────── │
│ 事故: [输入]  │  [事件1] [事件2] [事件3] ...       │
│ 延误: [输入]  │                                   │
│              │                                   │
│ ─ 驾驶场景 ── │                                   │
│ 场景: [下拉]  │                                   │
│              │                                   │
│ [保存预设]    │                                   │
├──────────────┴───────────────────────────────────┤
│  GraphQL Playground（内嵌 iframe）                 │
└──────────────────────────────────────────────────┘
```

### 5.2 功能

- **场景预设**：下拉选择预设场景（停车、城市驾驶、高速、拥堵），自动填充面板
- **自定义场景**：手动填写各字段，可保存为预设
- **工作流调试**：展示四个 Agent 各阶段的 JSON 输出
- **GraphQL Playground**：内嵌 Strawberry 自带的 GraphQL Playground，供高级查询
- 前端通过 GraphQL API 通信

### 5.3 技术实现

- 纯 HTML/CSS/JS 单页应用（同现有模式）
- 替换现有 `webui/index.html`
- 使用 `fetch` 调用 `/graphql` 端点
- 场景预设通过 GraphQL mutation 管理，持久化到 `data/scenario_presets.toml`

### 5.4 路由

- `/` → 新的模拟测试 WebUI
- 旧 WebUI 不保留（被新页面完全替代）
- `/graphql` → GraphQL 端点 + Playground

## 6. 路线图与本次范围

### 本次实施（核心）

| # | 任务 | 优先级 |
|---|------|--------|
| 1 | `app/schemas/context.py` — 上下文数据模型 + 场景预设模型 | P0 |
| 2 | GraphQL schema + resolvers | P0 |
| 3 | `AgentState` 扩展 + `AgentWorkflow` 改造（`run_with_stages`） | P0 |
| 4 | 轻量规则引擎 `app/agents/rules.py` + 规则合并 + prompt 注入 | P0 |
| 5 | `app/storage/init_data.py` 更新 — 新增 `scenario_presets.toml` 初始化 | P0 |
| 6 | 模拟测试 WebUI | P1 |
| 7 | 场景预设管理（CRUD via GraphQL） | P1 |
| 8 | 测试 | P0 |

### 未来规划（仅规划，不实施）

| 方向 | 说明 |
|------|------|
| 个性化学习冷启动 | 从外部系统导入用户画像数据，初始化策略权重 |
| 个性化漂移检测 | 在线更新与遗忘机制 |
| 隐私保护 | 本地化处理、脱敏、最小化存储 |
| 完整规则引擎 | 从硬编码规则升级为可配置规则（TOML 定义） |
| 对照实验框架 | 无系统 / 基础备忘 / 完整 Agent 的 A/B 测试 |

## 7. 依赖变更

```toml
# pyproject.toml 新增
dependencies = [
    # ... 现有依赖 ...
    "strawberry-graphql[fastapi]>=0.260.0",
]
```
