# 知行车秘 - 车载AI智能体原型系统

基于大语言模型的车载智能提醒与日程管理智能体，支持多Agent工作流、情境感知规则引擎和基于遗忘曲线的长期记忆管理。

---

## 目录

- [项目概述](#项目概述)
- [项目结构](#项目结构)
- [核心功能](#核心功能)
  - [多Agent工作流](#1-多agent工作流)
  - [上下文注入与规则引擎](#2-上下文注入与规则引擎)
  - [记忆检索系统](#3-记忆检索系统)
  - [扩展交互能力](#4-扩展交互能力)
  - [GraphQL API](#5-graphql-api)
  - [模拟测试工作台](#6-模拟测试工作台)
- [隐私保护](#隐私保护)
- [快速开始](#快速开始)
- [开发指南](#开发指南)
- [License](#license)

---

## 项目概述

知行车秘是一个车载AI智能体原型系统，专注于**驾驶场景下的智能提醒和日程管理**。系统基于多Agent协作工作流（Context → Task → Strategy → Execution），支持 MemoryBank 长期记忆管理策略，并通过请求级上下文注入实现外部数据（驾驶员状态、时空信息、交通状况）的集成。

### 设计目标

1. **驾驶安全优先**：轻量规则引擎基于驾驶员状态（疲劳、工作负荷、驾驶场景）自动约束提醒方式
2. **情境感知**：通过 GraphQL API 接收细粒度外部数据（经纬度、车速、ETA、拥堵等级），跳过 LLM 编造上下文
3. **遗忘曲线记忆**：基于 Ebbinghaus 遗忘曲线实现记忆衰减与强化，模拟人类记忆机制
4. **可解释决策**：四阶段工作流各节点输出可独立审查，支持用户反馈迭代优化
5. **交互灵活性**：支持多格式输出、主动触发、流式响应、多轮对话、快捷指令等多种交互模式

---

## 项目结构

```
DrivePal/
├── app/                          # 应用核心代码
│   ├── agents/                   # AI智能体核心模块
│   │   ├── workflow.py           # 多Agent工作流编排（四阶段流水线）
│   │   ├── state.py              # Agent状态类型定义 + WorkflowStages
│   │   ├── rules.py              # 轻量规则引擎（安全约束规则 + 合并策略）
│   │   ├── prompts.py            # 系统提示词模板
│   │   ├── outputs.py            # 多格式输出路由器（visual/audio/detailed）
│   │   ├── pending.py            # 待处理提醒管理器（主动触发）
│   │   ├── conversation.py       # 多轮对话管理（session-based）
│   │   ├── shortcuts.py          # 快捷指令解析器
│   │   └── probabilistic.py      # 概率推断（意图置信度 + 打断风险）
│   ├── api/                      # GraphQL API 层
│   │   ├── main.py               # FastAPI 应用入口 + GraphQL 挂载 + SSE 端点
│   │   ├── graphql_schema.py     # Strawberry schema 定义
│   │   ├── stream.py             # SSE 流式响应端点
│   │   └── resolvers/            # GraphQL resolvers
│   │       ├── query.py          #   Query resolvers
│   │       ├── mutation.py       #   Mutation resolvers
│   │       ├── errors.py         #   GraphQL 错误类
│   │       └── converters.py     #   输入类型转换器
│   ├── models/                   # AI模型封装
│   │   ├── chat.py               # LLM调用封装（多provider自动fallback，纯异步）
│   │   ├── embedding.py          # 嵌入模型封装（纯远程OpenAI兼容接口）
│   │   ├── settings.py           # 模型组/Provider配置加载
│   │   ├── model_string.py       # 模型字符串解析工具
│   │   ├── _http.py              # HTTP客户端共享超时配置（12h read timeout）
│   │   ├── types.py              # 纯数据类型（ProviderConfig等）
│   │   └── exceptions.py         # 模型异常定义
│   ├── memory/                   # 记忆模块
│   │   ├── memory.py             # MemoryModule Facade（工厂注册表 + per-user store）
│   │   ├── interfaces.py         # MemoryStore Protocol定义（含 close()）
│   │   ├── singleton.py          # 记忆模块单例（线程安全延迟初始化）
│   │   ├── types.py              # MemoryMode枚举（memory_bank）
│   │   ├── schemas.py            # 记忆数据模型定义
│   │   ├── utils.py              # 余弦相似度 + 事件hash
│   │   ├── privacy.py            # 位置脱敏工具
│   │   ├── embedding_client.py   # Embedding维度一致性检测
│   │   └── stores/               # 各记忆后端实现
│   │       └── memory_bank/      # MemoryBank后端
│   │           ├── store.py      #   MemoryStore Protocol 实现（Facade）
│   │           ├── index.py      #   FAISS 索引管理（IndexIDMap + IndexFlatIP）
│   │           ├── index_reader.py #   IndexReader Protocol（只读视图）
│   │           ├── retrieval.py  #   四阶段检索管道
│   │           ├── forget.py     #   遗忘曲线（Ebbinghaus + 概率模式）
│   │           ├── summarizer.py #   分层摘要与人格生成
│   │           ├── lifecycle.py  #   写入/遗忘/摘要编排
│   │           ├── config.py     #   集中配置（pydantic-settings）
│   │           ├── observability.py # 可观测性指标
│   │           ├── bg_tasks.py   #   后台任务管理器
│   │           └── llm.py        #   LLM 封装（上下文截断重试）
│   ├── schemas/                  # 通用数据模型
│   │   ├── context.py            # 驾驶上下文数据模型（DrivingContext等）
│   │   └── query.py              # 查询请求/响应数据模型
│   ├── storage/                  # 存储模块
│   │   ├── toml_store.py         # TOML文件存储引擎
│   │   ├── jsonl_store.py        # JSONL追加写存储
│   │   └── init_data.py          # 数据目录初始化
│   └── config.py                 # 应用配置
├── config/                       # 配置文件
│   ├── llm.toml                  # 模型组+Provider配置
│   ├── rules.toml                # 安全规则定义（数据驱动）
│   └── shortcuts.toml            # 快捷指令定义
├── data/                         # 数据目录（运行时生成）
├── experiments/                  # 实验模块
│   └── ablation/                 # 消融实验（规则引擎/架构/反馈学习）
├── tests/                        # 测试
├── webui/                        # 模拟测试工作台（Web UI）
├── archive/                      # 归档卷（论文旧稿，非命勿改）
└── pyproject.toml                # 项目配置
```

---

## 核心功能

### 1. 多Agent工作流

自定义四阶段流水线工作流，每个阶段由专门的Agent处理。**所有工作流方法均为异步（async/await）。**

```mermaid
flowchart LR
    A[用户输入] --> B[Context Agent]
    B --> C[Task Agent]
    C --> D[Strategy Agent]
    D --> E[Execution Agent]
```

#### Agent职责

| Agent | 输入 | 输出 | 说明 |
|-------|------|------|------|
| **Context Agent** | 用户输入 + 历史记忆 + 外部上下文 | JSON上下文对象 | 有外部数据时直接使用，无数据时 LLM 推断 |
| **Task Agent** | 用户输入 + 上下文 | JSON任务对象 | 事件抽取、类型归因（meeting/travel/shopping/contact/other） |
| **Strategy Agent** | 上下文 + 任务 + 安全约束 + 个性化策略 + 概率推断 | JSON决策对象 | 在安全约束范围内决定提醒时机、方式、内容 |
| **Execution Agent** | 决策对象 | 执行结果 + event_id | 存储事件，返回提醒内容，路由多格式输出 |

#### 工作流阶段输出

通过 `run_with_stages()` 方法获取各阶段的详细输出，用于调试和可解释性：

```python
result, event_id, stages = await workflow.run_with_stages(
    "明天上午9点有个会议",
    driving_context={"scenario": "highway", "driver": {"fatigue_level": 0.8}},
)
# stages.context / stages.task / stages.decision / stages.execution
```

---

### 2. 上下文注入与规则引擎

#### 外部上下文注入

通过 GraphQL API 的 `processQuery` mutation 传入 `DrivingContext`，包含细粒度驾驶环境数据：

| 数据类别 | 字段 | 说明 |
|----------|------|------|
| **驾驶员状态** | `emotion`, `workload`, `fatigue_level` | 情绪（5级）、工作负荷（4级）、疲劳度（0~1） |
| **时空信息** | `currentLocation`, `destination`, `etaMinutes`, `heading` | 经纬度、街道地址、车速 |
| **交通状况** | `congestionLevel`, `incidents`, `estimatedDelayMinutes` | 拥堵等级（4级）、事故列表 |
| **驾驶场景** | `scenario` | parked / city_driving / highway / traffic_jam |

当提供外部上下文时，Context Agent 跳过 LLM 推断，直接使用注入数据构建上下文对象。

#### 轻量规则引擎

规则引擎在 Task Agent 之后、Strategy Agent 之前执行，基于 `DrivingContext` 应用安全约束。规则通过 `config/rules.toml` 数据驱动加载（7 条内置规则），失败时回退 4 条核心硬编码规则：

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| 高速仅音频 | `scenario == "highway"` | `allowed_channels: [audio]`, `max_frequency: 30min` | 10 |
| 疲劳抑制 | `fatigue_level > 0.7`（可配） | `only_urgent: true`, `allowed_channels: [audio]` | 20 |
| 过载延后 | `workload == "overloaded"` | `postpone: true` | 15 |
| 停车全通道 | `scenario == "parked"` | `allowed_channels: [visual, audio, detailed]` | 5 |
| 城市驾驶限制 | `scenario == "city_driving"` | `allowed_channels: [audio]`, `max_frequency: 15min` | 8 |
| 拥堵安抚 | `scenario == "traffic_jam"` | `allowed_channels: [audio, visual]`, `max_frequency: 10min` | 7 |
| 乘客在场放宽 | `has_passengers && scenario != "highway"` | `extra_channels: [visual]` | 3 |

多规则匹配时按优先级合并：`allowed_channels` 取交集（空集回退 `{"visual", "audio", "detailed"}`），`extra_channels` 在交集后追加（去重），`max_frequency` 取最小值，`only_urgent` / `postpone` 取布尔或。

疲劳阈值可通过环境变量 `FATIGUE_THRESHOLD` 配置（默认 0.7）。规则后处理函数 `postprocess_decision()` 在 LLM 输出后强制执行，不可绕过。

#### 概率推断

条件启用的概率推断模块（`PROBABILISTIC_INFERENCE_ENABLED=1`，默认开启）在 Strategy Agent 前注入 prompt：

- **意图推断**：MemoryBank 检索 top-20 相似事件 → 按 type 聚合得分 → 归一化置信度分布
- **打断风险评估**：`0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed`，结果 ∈ [0,1]

---

### 3. 记忆检索系统

#### MemoryBank（FAISS 向量索引 + 遗忘曲线）

基于 MemoryBank 论文实现的三层记忆架构，使用 **FAISS IndexFlatIP** + **L2 归一化**（等价余弦相似度）的向量检索：

```mermaid
flowchart TD
    A[Interaction<br>原始交互] -->|聚合| B[Event<br>语义摘要]
    B -->|汇总| C[Summary<br>层级摘要]

    A:::interact
    B:::event
    C:::summary

    classDef interact fill:#f9f,stroke:#333,stroke-width:2px
    classDef event fill:#bbf,stroke:#333,stroke-width:2px
    classDef summary fill:#bfb,stroke:#333,stroke-width:2px
```

- **向量索引**：FAISS IndexIDMap(IndexFlatIP) + L2 归一化（精确内积搜索），自适应分块（P90×3 动态校准 chunk_size）
- **四阶段检索管道**：粗排（FAISS top-k ×4）→ 邻居合并（同 source 连续条目拼接）→ 重叠去重（并查集）→ 说话人感知降权（不匹配条目得分 ×0.75，负分 ×1.25）
- **遗忘曲线**：`retention = e^(-days / (time_scale × strength))`，`time_scale` 默认 1.0 可配置。确定性阈值模式（默认 `retention < 0.3` 标记遗忘），可选概率性模式（`MEMORYBANK_FORGET_MODE=probabilistic`）
- **回忆强化**：检索命中时 `memory_strength += 1`（无上限），增加记忆留存
- **自动聚合**：写入交互时基于 FAISS `_merged_indices` 重叠判定，满足则聚合至同一事件
- **分层摘要**：事件数达到日阈值后生成 daily_summary，达到总阈值后生成 overall_summary，附带人格画像
- **结果展开**：检索命中事件时，自动附加其关联的原始交互记录

#### 反馈学习机制

用户反馈（accept/ignore）会更新 `strategies.toml` 中的 `reminder_weights`：

- **accept**：对应事件类型权重 +0.1（上限 1.0）
- **ignore**：对应事件类型权重 -0.1（下限 0.1）

#### 与原始 MemoryBank 论文的实现对比

基于 [MemoryBank-SiliconFriend](https://github.com/zhongwanjun/MemoryBank-SiliconFriend)（论文 [MemoryBank: Enhancing Large Language Models with Long-Term Memory](https://arxiv.org/pdf/2305.10250.pdf)）实现。核心机制（遗忘曲线、记忆强化、双层摘要、人格分析）均已覆盖，同时在事件聚合、搜索评分等方面做了工程改进。详细对比分析见 [DEV.md - MemoryBank 实现差异分析](./DEV.md#memorybank-实现差异分析)。

---

### 4. 扩展交互能力

提供多种交互模式，满足驾驶场景下的不同使用需求。

#### 多格式输出与通道路由

Strategy Agent 输出支持三种格式的提醒内容，由 `OutputRouter` 根据规则引擎约束路由到合适通道：

| 格式 | 内容 | 适用场景 |
|------|------|---------|
| **visual** | 屏幕文字（简洁摘要 + 操作按钮） | 停车、拥堵等低负载场景 |
| **audio** | 语音播报（自然语言描述） | 高速、城市驾驶等视觉占用场景 |
| **detailed** | 详细图文（时间轴、地图等） | 停车深度查看 |

#### 主动触发框架

`PendingReminderManager` 管理未到触发条件的提醒，通过以下 trigger 类型触发：

| 触发类型 | 说明 |
|---------|------|
| **time** | 绝对时间触发（"下午3点提醒我"） |
| **location** | 到达目的地附近触发（"到国贸提醒我"） |
| **delay** | 相对延时触发（"5分钟后提醒我"） |

通过 `pollPendingReminders` mutation 轮询检查触发条件，支持 TTL 过期自动取消。

#### SSE 流式响应

端点 `GET /query/stream` 返回 Server-Sent Events，按 Agent 阶段推送进度事件：

```
event: stage
data: {"stage": "context", "status": "running"}

event: stage
data: {"stage": "context", "status": "done", "output": {...}}

event: done
data: {"result": "...", "event_id": "..."}
```

#### 多轮对话

`ConversationManager` 通过 `sessionId` 追踪连续对话，`closeSession(sessionId)` 清理会话状态。

#### 快捷指令

`config/shortcuts.toml` 定义常用快捷指令（静音、延后、报告状态等），由 `ShortcutResolver` 解析并路由至对应逻辑。安全旁路 guard 确保规则约束仍被遵守。

---

### 5. GraphQL API

基于 [Strawberry GraphQL](https://strawberry.rocks/) 的 code-first GraphQL API，与 FastAPI 集成。

#### 基础信息

- 端点：`/graphql`（GraphQL Playground 可用）
- SSE 端点：`/query/stream`
- 服务启动：`uv run uvicorn app.api.main:app`（默认 `0.0.0.0:8000`）

#### Query

```graphql
type Query {
  history(limit: Int = 10, memoryMode: MemoryMode! = MEMORY_BANK): [MemoryEvent!]!
  scenarioPresets: [ScenarioPreset!]!
}
```

#### Mutation

```graphql
type Mutation {
  processQuery(input: ProcessQueryInput!): ProcessQueryResult!
  submitFeedback(input: FeedbackInput!): FeedbackResult!
  saveScenarioPreset(input: ScenarioPresetInput!): ScenarioPreset!
  deleteScenarioPreset(id: String!): Boolean!
  pollPendingReminders: [PendingReminder!]!
  cancelPendingReminder(id: String!): Boolean!
  getPendingReminders: [PendingReminder!]!
  closeSession(sessionId: String!): Boolean!
  exportData(currentUser: String!): ExportDataResult!
  deleteAllData(currentUser: String!): Boolean!
}
```

#### processQuery input 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | String! | 用户输入文本 |
| `memoryMode` | MemoryMode! | 记忆模式（默认为 MEMORY_BANK） |
| `context` | DrivingContextInput | 可选外部驾驶上下文（跳过 LLM 推断） |
| `sessionId` | String | 可选多轮对话 session 标识 |
| `currentUser` | String | 用户标识（默认 "default"） |

#### 核心查询示例 — 带上下文注入

```graphql
mutation {
  processQuery(input: {
    query: "明天上午9点有个会议"
    memoryMode: MEMORY_BANK
    context: {
      driver: { emotion: "calm", workload: "normal", fatigueLevel: 0.2 }
      spatial: {
        currentLocation: { latitude: 39.9042, longitude: 116.4074, address: "北京市东城区", speedKmh: 0 }
        destination: { latitude: 39.9142, longitude: 116.4174, address: "国贸大厦" }
        etaMinutes: 25
      }
      traffic: { congestionLevel: "smooth", incidents: [], estimatedDelayMinutes: 0 }
      scenario: "parked"
    }
  }) {
    result eventId
    stages { context task decision execution }
  }
}
```

#### 场景预设管理

```graphql
# 保存预设
mutation { saveScenarioPreset(input: { name: "高速驾驶", context: { scenario: "highway" } }) { id name } }

# 加载预设
query { scenarioPresets { id name context { scenario driver { emotion } } } }

# 删除预设
mutation { deleteScenarioPreset(id: "abc123") }
```

---

### 6. 模拟测试工作台

基于纯 HTML/CSS/JavaScript 的单页应用，作为场景模拟与工作流调试工具：

- **场景配置面板**：配置驾驶员状态、时空信息、交通状况、驾驶场景
- **场景预设**：保存/加载模拟场景，快速切换测试场景
- **工作流调试**：展示四个 Agent 各阶段的 JSON 输出（Context/Task/Strategy/Execution）
- **反馈按钮**：接受/忽略提醒，验证反馈学习机制
- **历史记录**：查看最近交互记录
- **GraphQL Playground**：通过底部链接访问高级查询界面

#### 启动方式

WebUI 由 FastAPI 静态文件服务托管，无需单独构建或启动前端开发服务器。数据目录在服务启动时自动初始化。

```bash
# 1. 安装依赖（首次）
uv sync

# 2. 启动服务
uv run uvicorn app.api.main:app
```

- 模拟测试工作台：http://localhost:8000
- GraphQL Playground：http://localhost:8000/graphql
- SSE 流式端点：http://localhost:8000/query/stream

---

## 隐私保护

- 所有数据存储在本地 `data/users/` 目录下
- 无云端同步、无遥测、无第三方数据共享
- LLM 调用不发送原始记忆数据至外部——仅发送当前查询文本、规则约束及必要上下文摘要
- 位置信息自动脱敏：经纬度截断至小数点后 2 位（约 1km 精度），地址保留街道级
- 支持通过 GraphQL `exportData` / `deleteAllData` 导出或删除个人数据

---

## 快速开始

### 环境要求

- Python 3.14+
- 本地部署 vLLM（Qwen3.5-2B）或 OpenAI 兼容 API

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置

编辑 `config/llm.toml` 中的 `model_providers` 和 `model_groups`。也可通过环境变量覆盖：

```bash
# 示例：设置 MiniMax API Key（用于 balanced 模型组）
export MINIMAX_API_KEY="your-api-key"
```

### 3. 启动Web服务

数据目录在服务启动时自动初始化，无需手动操作。

```bash
uv run uvicorn app.api.main:app
```

- 模拟测试工作台：http://localhost:8000
- GraphQL Playground：http://localhost:8000/graphql

---

## 开发指南

详见 [DEV.md](./DEV.md)。

---

## License

MIT
