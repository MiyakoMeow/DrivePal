# 上下文注入与模拟测试工作台设计

## 背景

开题报告提出四层架构（情境建模层 → 任务理解层 → 策略决策层 → 执行与反馈层），当前实现中情境建模层完全依赖 LLM 编造上下文，缺乏真实外部数据注入。本设计补齐该缺口，并提供模拟测试页面用于场景验证。

## 核心决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据注入方式 | 请求级上下文注入 | 无状态、易测试、外部对接自然 |
| API 风格 | GraphQL（Strawberry + FastAPI） | 强类型 schema、按需查询字段、便于复杂嵌套上下文数据、前端灵活组装 |
| 策略决策 | 轻量规则 + LLM | 关键安全约束走规则，其余 LLM 生成 |
| 时空数据粒度 | 细粒度（坐标级） | 支持精确场景模拟 |
| WebUI 定位 | 场景模拟 + 工作流调试 | 可视化各 Agent 阶段输出 |

## 1. 数据模型

新增 `app/schemas/context.py`，定义外部上下文数据结构。

```python
class DriverState(BaseModel):
    emotion: str = "neutral"        # neutral / anxious / fatigued / calm / angry
    workload: str = "normal"        # low / normal / high / overloaded
    fatigue_level: float = 0.0      # 0.0 ~ 1.0

class GeoLocation(BaseModel):
    latitude: float = 0.0
    longitude: float = 0.0
    address: str = ""
    speed_kmh: float = 0.0

class SpatioTemporalContext(BaseModel):
    current_location: GeoLocation = GeoLocation()
    destination: GeoLocation | None = None
    eta_minutes: float | None = None
    heading: float | None = None    # 行驶方向 0~360

class TrafficCondition(BaseModel):
    congestion_level: str = "smooth"  # smooth / slow / congested / blocked
    incidents: list[str] = []
    estimated_delay_minutes: int = 0

class DrivingContext(BaseModel):
    driver: DriverState = DriverState()
    spatial: SpatioTemporalContext = SpatioTemporalContext()
    traffic: TrafficCondition = TrafficCondition()
    scenario: str = "parked"        # parked / city_driving / highway / traffic_jam
```

`DrivingContext` 可选 — 不传时走原有纯 LLM 推断路径，向后兼容。

## 2. GraphQL API 层

使用 Strawberry GraphQL 库与 FastAPI 集成，替换现有 REST API。

### 2.1 技术选型

- **Strawberry**：code-first GraphQL 库，原生支持 Pydantic 模型转换，与 FastAPI 无缝集成
- 依赖：`strawberry-graphql[fastapi]`

### 2.2 Schema 定义

```graphql
type Query {
  history(limit: Int = 10, memoryMode: MemoryMode! = MEMORY_BANK): [MemoryEvent!]!
  experimentReport: ExperimentReport!
  # 获取可用的模拟场景预设
  scenarioPresets: [ScenarioPreset!]!
}

type Mutation {
  # 核心查询（含上下文注入）
  processQuery(input: ProcessQueryInput!): ProcessQueryResult!
  # 提交反馈
  submitFeedback(input: FeedbackInput!): FeedbackResult!
  # 场景预设管理（用于模拟测试）
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
  # 工作流各阶段输出（调试用）
  stages: WorkflowStages
}

type WorkflowStages {
  context: JSON!
  task: JSON!
  decision: JSON!
  execution: JSON!
}

input FeedbackInput {
  eventId: String!
  action: String!   # accept | ignore
  modifiedContent: String
}

type FeedbackResult {
  status: String!
}
```

### 2.3 与现有 REST API 的关系

- GraphQL 端点挂载在 `/graphql`，同时保留原有 REST 端点（标记 deprecated）
- GraphQL playground 自动可用（Strawberry 提供），便于开发调试
- 新功能仅通过 GraphQL 暴露

### 2.4 文件结构

```
app/api/
├── main.py              # FastAPI app，挂载 GraphQL router
├── graphql_schema.py    # Strawberry schema 定义（type/mutation/query）
├── resolvers/
│   ├── __init__.py
│   ├── query.py         # Query resolvers
│   └── mutation.py      # Mutation resolvers
```

## 3. 工作流改造

### 3.1 AgentWorkflow 接受外部上下文

`AgentWorkflow.run()` 签名扩展：

```python
async def run(
    self,
    user_input: str,
    driving_context: DrivingContext | None = None,
) -> tuple[str, str | None, dict]:
    # ...
    # 返回值新增第三个元素：各阶段输出（用于调试）
```

### 3.2 Context Node 使用真实数据

当 `driving_context` 非空时：
- 跳过 LLM 生成上下文
- 将 `DrivingContext` 序列化为 JSON 直接作为 context
- prompt 中标注"以下为真实传感器/系统注入数据，请直接使用"

当 `driving_context` 为空时：
- 走原有 LLM 推断路径（向后兼容）

### 3.3 各阶段输出收集

新增 `WorkflowStages` 数据类，工作流执行过程中逐步填充：

```python
@dataclass
class WorkflowStages:
    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
```

## 4. 轻量规则引擎

在 Strategy Agent 之前，基于 `DrivingContext` 应用安全约束规则。

### 4.1 规则定义

```python
# app/agents/rules.py

SAFETY_RULES: list[Rule] = [
    # 高速行驶 → 仅允许 audio 提醒，禁止 visual
    Rule(
        condition=lambda ctx: ctx.scenario == "highway",
        constraint={"allowed_channels": ["audio"], "max_frequency": "30min"},
    ),
    # 疲劳等级 > 0.7 → 抑制非紧急提醒
    Rule(
        condition=lambda ctx: ctx.driver.fatigue_level > 0.7,
        constraint={"only_urgent": True, "channels": ["audio"]},
    ),
    # 工作负荷 overloaded → 延后提醒
    Rule(
        condition=lambda ctx: ctx.driver.workload == "overloaded",
        constraint={"postpone": True, "postpone_until": "workload_normal"},
    ),
    # 停车状态 → 允许所有通道和详细内容
    Rule(
        condition=lambda ctx: ctx.scenario == "parked",
        constraint={"allowed_channels": ["visual", "audio", "detailed"]},
    ),
]
```

### 4.2 应用时机

```
Context Node → Task Node → [Rule Engine] → Strategy Node → Execution Node
```

规则引擎在 Task Node 之后、Strategy Node 之前执行：
1. 遍历匹配的规则，收集 constraints
2. 将 constraints 注入 Strategy prompt 作为硬性约束
3. Strategy Agent 必须在约束范围内决策

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
- 使用 `fetch` 调用 `/graphql` 端点
- 场景预设存储在服务端（`data/scenario_presets.toml`）

## 6. 路线图与本次范围

### 本次实施（核心）

| # | 任务 | 优先级 |
|---|------|--------|
| 1 | `app/schemas/context.py` — 上下文数据模型 | P0 |
| 2 | GraphQL schema + resolvers | P0 |
| 3 | `AgentWorkflow` 接受外部上下文 + 阶段输出收集 | P0 |
| 4 | 轻量规则引擎 `app/agents/rules.py` | P0 |
| 5 | 模拟测试 WebUI | P1 |
| 6 | 场景预设管理（CRUD） | P1 |
| 7 | 测试 | P0 |

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
