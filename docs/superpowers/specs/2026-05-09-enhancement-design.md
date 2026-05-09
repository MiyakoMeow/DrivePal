# 知行车秘增强方案设计文档 v2

日期：2026-05-09
目标：补六缺口 + 加四新能力，8周内完成，工程完整性优先

v2 变更说明：不保留向后兼容，采用全栈 per-user 目录隔离、嵌入向量意图推断、数据驱动规则三项架构改进。

---

## 一、背景

开题报告规划四大层（情境建模、任务理解、策略决策、执行反馈），与中期报告对照后发现六缺口：

1. 反馈学习 no-op
2. 规则引擎仅 4 场景
3. 概率推断被移除
4. 隐私保护未实现
5. 多用户上层隔离未实现 — MemoryBank 底层 per-user store（`MemoryModule.get_store(user_id)` + `user_{user_id}` 子目录）已由 PR #120 交付；上层 JSONL/TOML/API 待扩展
6. 突发事件处理无独立模块（已由现有机制覆盖，仅需文档说明）

新增四能力：概率推断模块、隐私保护方案、多用户场景、实验数据可视化。缺口 3/4 同时属于新增能力。缺口 5 上层部分由新增能力 3.3 覆盖。

**架构改进（v2）**：三项根本性改进替代原设计中的部分方案——

| 改进 | 影响章节 | 说明 |
|------|---------|------|
| 全栈 per-user 目录隔离 | §3.3, §3.2, §2.1 | 替代半隔离 + user_id 字段方案 |
| 嵌入向量意图推断 | §3.1 | 替代关键词+朴素贝叶斯方案 |
| 数据驱动规则 | §2.2 | 规则从 TOML 加载，替代硬编码 |

---

## 二、缺口补漏

### 2.1 反馈学习恢复

**问题**：`MemoryBankStore.update_feedback()` 为 `pass`。

**方案**：`update_feedback` 更新事件级 feedback 记录（`feedback.jsonl`）；权重更新逻辑在 mutation resolver 层（`submit_feedback`）执行——resolver 打开对应 `strategies.toml` 读→更新→写回，不污染 MemoryBankStore 职责。

- accept → `reminder_weights[event_type] += 0.1`（上限 1.0）
- ignore → `reminder_weights[event_type] -= 0.1`（下限 0.1）
- 不存在的事件类型初始权重为 0.5（上下限 0.1/1.0 的中点）
- 权重通过 `TOMLStore.update("reminder_weights", merged_weights_dict)` 整表覆盖写回 `strategies.toml`

**设计理由**：MemoryBankStore 职责为记忆存储/检索，不应耦合偏好策略（`strategies.toml` 属策略层）。resolver 层协调两存储（MemoryBank for feedback 记录，TOMLStore for 权重更新），保持模块边界清晰。
- Strategy Agent 读取权重时偏好高权重事件类型

**与 §3.3 的交互**：全栈 per-user 目录隔离后，每个用户有独立 `data/users/{user_id}/strategies.toml`，无需虚线键，无需 `currentUser` 参数判断写入路径——store 打开对应用户文件即可。

**改动文件**：
- `app/memory/memory_bank/store.py`：`update_feedback` 实现（记录 feedback 数据到 `feedback.jsonl`，不影响事件 memory_strength）
- `app/api/resolvers/mutation.py`：`submit_feedback` 中新增 `strategies.toml` 权重更新逻辑
- `app/storage/init_data.py`：per-user 目录初始化含 `strategies.toml`（`reminder_weights = {}`）
- `tests/stores/test_memory_bank_store.py`：补 feedback 记录测试
- `tests/test_mutation_feedback.py`：补 accept/ignore 权重变化端到端测试

### 2.2 规则引擎补全 + 数据驱动

**问题**：`SAFETY_RULES` 仅 4 条，硬编码 lambda 列表，city_driving 和 traffic_jam 场景无专属规则。

**方案**：规则从 `config/rules.toml` 加载，`rules.py` 解析为 `Rule` 对象。新增 2 条规则 + 1 条乘客规则（原在 §3.3）。

```toml
# config/rules.toml — 安全约束规则定义
[[rules]]
name = "highway_audio_only"
scenario = "highway"
allowed_channels = ["audio"]
max_frequency_minutes = 30
priority = 10

[[rules]]
name = "fatigue_suppress"
fatigue_above = 0.7
only_urgent = true
allowed_channels = ["audio"]
priority = 20

[[rules]]
name = "overloaded_postpone"
workload = "overloaded"
postpone = true
priority = 15

[[rules]]
name = "parked_all_channels"
scenario = "parked"
allowed_channels = ["visual", "audio", "detailed"]
priority = 5

[[rules]]
name = "city_driving_limit"
scenario = "city_driving"
allowed_channels = ["audio"]
max_frequency_minutes = 15
priority = 8

[[rules]]
name = "traffic_jam_calm"
scenario = "traffic_jam"
allowed_channels = ["audio", "visual"]
max_frequency_minutes = 10
priority = 7

[[rules]]
name = "passenger_present_relax"
has_passengers = true
not_scenario = "highway"
extra_channels = ["visual"]
priority = 3
```

**条件字段说明**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `scenario` | str | 匹配 `DrivingContext.scenario` |
| `not_scenario` | str | 排除该场景 |
| `workload` | str | 匹配 `driver.workload` |
| `fatigue_above` | float | `driver.fatigue_level > 此值` |
| `has_passengers` | bool | `DrivingContext.passengers` 非空 |

所有条件为 AND 关系。不支持 lambda/自定义函数——当前规则全集已覆盖所有需求。

**边界行为**：
- `not_scenario` 条件仅在 `DrivingContext.scenario` 字段存在且非空时求值；scenario 缺失时规则不匹配（乘客在场规则不会在无场景信息时意外触发）
- `fatigue_above` 仅在 `driver.fatigue_level` 存在时为 True 比较；缺失时条件不满足
- `has_passengers` 仅在 `DrivingContext.passengers` 字段存在且非空时为 True

**配置加载 fallback**：`load_rules()` 读取 `config/rules.toml` 失败时（文件缺失/格式错），回退到硬编码的 4 条默认规则（highway_audio_only / fatigue_suppress / overloaded_postpone / parked_all_channels），并日志警告。保证系统在配置文件损坏时仍可安全运行。

**解析逻辑**：`rules.py` 新增 `load_rules(path) -> list[Rule]`，读取 TOML 并构造 `Rule` 对象（`condition` 为闭包合成）。`SAFETY_RULES` 改为模块级变量，由 `load_rules()` 初始化。

**合并策略**：
- `allowed_channels`：所有匹配规则的 `allowed_channels` 取交集；空集回退默认 `[visual, audio, detailed]`；交集后追加所有匹配规则的 `extra_channels`（去重）
- `only_urgent` / `postpone`：任意规则匹配即取 True（布尔或）
- `max_frequency_minutes`：所有含该字段的匹配规则取最小值（最严格）；不含该字段的规则不影响合并结果
- 优先级：仅用于 `apply_rules()` 对多条匹配规则的排序与优先级指示——高优先级规则的约束不覆盖低优先级，合并逻辑为上述取交/取或/取最严

**合并验证**：
- city_driving(max=15) + fatigue(无 max) → `max=15`, `only_urgent=true`, `channels=[audio]`
- traffic_jam(max=10) + overloaded(无 max) → `max=10`, `postpone=true`（overloaded 的 postpone 不消除 max 频次约束）
- city_driving + passenger → `channels=[audio] + extra [visual] = [audio, visual]`；`max=15`（city_driving 提供）
- highway(max=30) + city_driving(max=15)（不应同时发生，但若意外） → `max=min(30,15)=15`

**额外通道语义**：`extra_channels` 字段不参与 `allowed_channels` 取交集，而是在交集结果上追加。适用场景：乘客在场放宽通道时，安全规则（如 city_driving 限制 audio）仍优先，但乘客在场追加 visual。

**`apply_rules` 合并逻辑变更**：新增对 `extra_channels` 的处理——在所有 `allowed_channels` 交集完成后，收集所有匹配规则中的 `extra_channels`，追加到结果中（去重）。修改点在 `rules.py` 的 `apply_rules()` 函数末尾。

**频次约束执行点**：`max_frequency_minutes` 由 Execution Agent 在发送提醒前检查——查询当前场景下最近一次提醒时间，若间隔小于 `max_frequency_minutes` 则抑制本次提醒。实现位置：`app/agents/workflow.py` 的 `_execution_node`。

**改动文件**：
- `config/rules.toml`：**新增**
- `app/agents/rules.py`：加 `load_rules()` + 解析逻辑，`SAFETY_RULES` 改为从配置加载
- `tests/test_rules.py`：补 7 条规则全覆盖测试

### 2.3 突发事件处理（文档处置）

**问题**：开题规划"突发事件处理"，无独立模块。

**处置**：Strategy Agent 语义推理 + 规则引擎（postpone/only_urgent）联合覆盖。论文中说明此设计决策。更新 AGENTS.md 未解决问题列表。

---

## 三、新能力设计

### 3.1 概率推断模块

**背景**：开题规划"规则/阈值 + 概率推断 + 大模型生成"混合策略。实际仅有规则+LLM，概率推断层缺失。

**架构位置**：
```
DrivingContext → 规则引擎 → 概率推断 → LLM 策略决策 → postprocess_decision
                  (硬约束)    (软建议)    (语义推理)     (硬覆盖)
```

**推断两类**：

**A. 意图不确定性**

输入：当前查询文本 + 用户历史记忆（MemoryBank 检索结果）。输出：意图置信度 + 备选事件类型。

算法（嵌入向量相似度推断，无新依赖——复用既有 embedding + FAISS）：

1. 调用 `MemoryBankStore.search(query_text, top_k=20)` 检索相似历史事件（`search()` 内部完成文本编码和 FAISS 检索，返回 `list[SearchResult]`，每个 `SearchResult.score` 为余弦相似度）
2. 按事件 type 聚合相似度得分：`type_score[t] = Σ result.score` for all results where result.event.type == t
3. 归一化得置信度分布：`confidence[t] = type_score[t] / Σ type_score`
4. 最高分为主意图，次高为备选解释

冷启动（检索无结果或 top_k 空）：所有类型等概率，依赖 LLM 语义推理兜底。

**B. 打断风险**

输入：`DrivingContext` 现有字段。输出：0~1 风险分数。

公式：`0.4 × fatigue_level + 0.3 × workload_score + 0.2 × scenario_risk + 0.1 × speed_factor`

枚举到数值映射表：

| workload | workload_score |
|----------|---------------|
| low | 0.1 |
| normal | 0.3 |
| high | 0.6 |
| overloaded | 0.9 |

| scenario | scenario_risk |
|----------|--------------|
| parked | 0.0 |
| city_driving | 0.4 |
| traffic_jam | 0.3 |
| highway | 0.7 |

| speed (km/h) | speed_factor |
|-------------|-------------|
| 0 | 0.0 |
| 1~40 | 0.3 |
| 41~80 | 0.5 |
| >80 | 0.8 |

**边界说明**：overloaded 场景由规则引擎 `postpone` 在前置拦截，概率推断模块运行时不应出现 workload==overloaded。若因旁路调用而意外出现，workload_score 仍取 0.9（防御性），interrupt_risk ≥ 0.36 时在注入 prompt 中附加"高打断风险"警告标记，但不改变规则引擎的 postpone 决策。`scenario` 缺失或 None 时 `scenario_risk` 取 0.5（保守中等风险，防御空上下文的极端情况）。

`interrupt_risk ≥ 0.36` 阈值来源于 `fatigue_level=0.7 × 0.4 + workload=normal × 0.3 + scenario=city × 0.2 ≈ 0.45`（疲劳阈值临界附近典型场景）——此值可在实现阶段调整，设计文档提供参考基线。

**输出注入方式**：结构化 JSON 注入 Strategy Agent prompt。
```json
{"intent_confidence": 0.72, "alternative": "travel", "alt_confidence": 0.20, "interrupt_risk": 0.23}
```

**关键约束**：
- 不替代规则引擎硬约束。`postprocess_decision` 仍在最后执行
- 不修改工作流节点顺序
- 环境变量 `PROBABILISTIC_INFERENCE_ENABLED` 控制（默认开启，支持消融实验）
- 意图推断使用嵌入相似度聚合，不使用 `reminder_weights`——两者语义不同（统计 vs 偏好）
- **不在 MemoryBankStore 新增 API**——复用既有 `search()` 方法即可

**实现文件**：
- 新 `app/agents/probabilistic.py`（~40 行，search→aggregate→normalize）
- 改 `app/agents/workflow.py`：`_strategy_node` 调用推断
- 测试 `tests/test_probabilistic.py`
- 注意：概率推断结果由 workflow 动态拼入 prompt，不修改 `prompts.py`（与现有 constraints/strategies 注入方式一致）

**无外部依赖**：embedding 模型为系统既有依赖，FAISS 检索为 MemoryBank 既有能力。

### 3.2 隐私保护方案

**三层设计**：

**第一层：声明式隐私标记**

在写入记忆前自动脱敏位置信息：
- 经纬度截断至小数点后 2 位（约 1km 精度）
- 地址只保留街道级
- 新 `app/memory/privacy.py` 提供脱敏工具

**第二层：数据可携带性**

新增 GraphQL mutation：
```graphql
mutation {
  exportData(currentUser: String): ExportDataResult     # 导出指定用户全量数据
  deleteAllData(currentUser: String): Boolean           # 删除指定用户全量数据
}
```

`ExportDataResult` 返回 `{files: JSON}`，其中 files 为 `{filename: content_string}` 映射。不包含二进制文件（index.faiss）。导出范围：`data/users/{currentUser}/` 下所有文本文件。

`deleteAllData` 删除 `data/users/{currentUser}/` 整个目录（含 MemoryBank 子目录）。`currentUser` 为必填参数——无默认值，显式指定防止误删。实验数据 `data/experiment_benchmark.toml` 不受影响（全局文件，非用户数据）。

**不再需要的复杂说明**：全栈 per-user 目录隔离后，导/删即单目录操作，无需"仅删 MemoryBank 不删共享文件"等 caveat。

**第三层：本地优先声明**

在 AGENTS.md 和 README 中明确声明：
- 所有数据本地存储
- 无云端同步、无遥测、无第三方共享
- LLM 调用不发送原始记忆数据至外部——仅发送当前查询文本、规则约束及必要驾驶上下文摘要；用户可关闭记忆功能（`MemoryMode.NONE`）进一步限制数据暴露

**不做**：加密存储、差分隐私、GDPR 全栈合规（原型系统）。

**改动文件**：
- 新 `app/memory/privacy.py`
- 改 `app/api/graphql_schema.py`：加 `exportData`/`deleteAllData` 类型
- 改 `app/api/resolvers/mutation.py`：加 resolver
- 测试 `tests/test_privacy.py`
- 文档 AGENTS.md/README.md

### 3.3 多用户场景 — 全栈 per-user 目录隔离

**背景**：PR #120 已交付 MemoryBank 底层 per-user store 隔离。上层 JSONL/TOML 文件、API、策略、规则仍为单用户设计。采用全栈目录隔离替代原方案的 user_id 字段打补丁。

**目录结构**：

```
data/
├── users/
│   ├── default/                    # 默认用户（原 data/ 下所有文件迁入）
│   │   ├── events.jsonl
│   │   ├── interactions.jsonl
│   │   ├── feedback.jsonl
│   │   ├── contexts.toml
│   │   ├── preferences.toml
│   │   ├── strategies.toml         # [reminder_weights] 扁平，无需虚线键
│   │   ├── scenario_presets.toml
│   │   └── memorybank/             # PR #120 已隔离，移入此
│   │       ├── index.faiss
│   │       ├── metadata.json
│   │       └── extra_metadata.json
│   └── 张三/
│       └── ... (同 default/)
└── experiment_benchmark.toml         # 全局共享，非用户数据
```

**设计理由**：
- 目录即隔离边界，记录无需 user_id 字段——减少读写路径中的条件分支
- `deleteAllData` = `rm -rf data/users/{user_id}`，干净彻底
- `exportData` = 序列化单目录，无跨用户数据泄露
- `strategies.toml` 自然 per-user，无需虚线键
- `TOMLStore`/`JSONLStore` 构造函数接受 per-user 目录路径，其余无感

**API 层变更**：
- `ProcessQueryInput`、`FeedbackInput` 新增必填字段 `currentUser: String`；`currentUser = "default"` 时为单用户模式
- `history` query 和 `scenarioPresets` query 新增 `currentUser` 参数，路由到 `data/users/{currentUser}/` 下的对应数据
- `saveScenarioPreset`、`deleteScenarioPreset` mutation 新增 `currentUser` 参数，preset store 路径改为 per-user
- resolver 根据 `currentUser` 确定 `data/users/{currentUser}/` 数据目录
- `MemoryModule.get_store(currentUser)` 打开 per-user MemoryBank

**存储层变更**：
- `TOMLStore.__init__()` 和 `JSONLStore.__init__()` 新增 `user_dir: Path` 参数
- 新增 `init_user_dir(user_id: str)` 在首次使用时创建 `data/users/{user_id}/` 目录结构
- 在 `app/storage/init_data.py` 中实现

**规则层**：新增乘客在场规则（已在 §2.2 `config/rules.toml` 中定义，使用 `has_passengers` 条件）。

**DrivingContext 扩展**：
- `DrivingContext` 新增 `passengers: list[str] = []` 字段
- `DrivingContextInput` 和 `DrivingContextGQL` 类型需同步新增 `passengers` 字段

**检索管道**：不改（speaker 字段已就绪）。

**摘要/人格**：已按用户分组分析（MemoryBank per-user 隔离自带）。

**迁移路径**：
1. 创建 `data/users/default/` 目录
2. 移动 `data/*.jsonl`、`data/*.toml` 至 `data/users/default/`
3. 若 `data/memorybank/` 存在且含 `user_*/` 子目录（PR #120 已创建的 per-user 结构），按 `data/memorybank/user_{id}/` → `data/users/{id}/memorybank/` 映射逐用户迁入；若仅含平铺文件（无 `user_*/`），整体移至 `data/users/default/memorybank/`
4. `experiment_benchmark.toml` 和 `webui/` 留在 `data/` 根目录
5. 迁移逻辑作为 `init_data.py` 的一部分，幂等——已迁移则跳过

**改动文件**：
- 改 `app/storage/toml_store.py`：构造函数接受 `user_dir`
- 改 `app/storage/jsonl_store.py`：构造函数接受 `user_dir`
- 改 `app/storage/init_data.py`：加 `init_user_dir()` + 迁移逻辑
- 改 `app/api/graphql_schema.py`：`ProcessQueryInput`、`FeedbackInput` 加 `currentUser`
- 改 `app/api/resolvers/mutation.py`：传递 `currentUser`
- 改 `app/agents/workflow.py`：接收并传递 `currentUser`
- 改 `app/schemas/context.py`：`DrivingContext` 加 `passengers`
- 改 `app/config.py`：`DATA_DIR` 逻辑支持 per-user 子路径
- 测试 `tests/test_multi_user.py`

### 3.4 实验数据可视化

**数据格式**：`data/experiment_benchmark.toml`，用户从 VehicleMemBench 手动填入。注意：此文件与现有 `data/experiment_results.jsonl`（实验运行日志，JSONL 格式）不同——前者为用户手工填入的可视化数据，后者为系统自动记录。本模块仅读取前者。
```toml
# experiment_benchmark.toml — 五策略对比数据（手工填入）
[strategies.none]
exact_match = 0.0
field_f1 = 0.0
value_f1 = 0.0

[strategies.gold]
exact_match = 1.0
field_f1 = 1.0
value_f1 = 1.0

[strategies.summary]
exact_match = 0.0
field_f1 = 0.0
value_f1 = 0.0

[strategies.key_value]
exact_match = 0.0
field_f1 = 0.0
value_f1 = 0.0

[strategies.memory_bank]
exact_match = 0.52
field_f1 = 0.71
value_f1 = 0.67
```

**GraphQL 查询**：`experimentResults` 返回五策略对比数据。

Strawberry 类型：
```python
@strawberry.type
class ExperimentResult:
    strategy: str          # "none" | "gold" | "summary" | "key_value" | "memory_bank"
    exact_match: float
    field_f1: float
    value_f1: float

@strawberry.type
class ExperimentResults:
    strategies: list[ExperimentResult]
```

**WebUI 可视化**：
- 新增「实验结果」标签页
- Chart.js（CDN，无构建步骤）
- 五策略并排柱状图（Exact Match / Field F1 / Value F1）
- 高亮本系统（MemoryBank）

**改动文件**：
- 新 `app/storage/experiment_store.py`
- 改 `app/api/graphql_schema.py`：`ExperimentResults` 类型
- 改 `app/api/resolvers/query.py`：`experimentResults` query
- 改 `webui/index.html` + `webui/app.js`：图表面板
- 测试 `tests/test_experiment_results.py`

---

## 四、文件变更汇总

| 文件 | 变更类型 | 关联需求 |
|------|---------|---------|
| `config/rules.toml` | **新增** | 2.2 数据驱动规则 |
| `app/agents/rules.py` | 重写 | 2.2 TOML 加载 + 解析 |
| `app/agents/workflow.py` | 修改 | 3.1 概率推断, 3.3 多用户 |
| `app/agents/probabilistic.py` | **新增** | 3.1 概率推断 |
| `app/memory/memory_bank/store.py` | 修改 | 2.1 反馈（仅记录 feedback，不写 strategies.toml） |
| `app/memory/privacy.py` | **新增** | 3.2 隐私保护 |
| `app/schemas/context.py` | 修改 | 3.3 多用户（passengers） |
| `app/storage/toml_store.py` | 修改 | 3.3 per-user 目录 |
| `app/storage/jsonl_store.py` | 修改 | 3.3 per-user 目录 |
| `app/storage/init_data.py` | 修改 | 2.1 初始 strategies.toml, 3.3 目录初始化 + 迁移 |
| `app/storage/experiment_store.py` | **新增** | 3.4 实验可视化 |
| `app/config.py` | 修改 | 3.3 per-user DATA_DIR |
| `app/api/graphql_schema.py` | 修改 | 3.2 导出/删除, 3.3 currentUser（Query + Mutation Input）, 3.4 实验结果 |
| `app/api/resolvers/query.py` | 修改 | 3.3 currentUser, 3.4 实验可视化 |
| `app/api/resolvers/mutation.py` | 修改 | 2.1 反馈权重更新, 3.2 导出/删除, 3.3 currentUser |
| `webui/index.html` | 修改 | 3.4 实验可视化 |
| `webui/app.js` | 修改 | 3.4 实验可视化 |
| `AGENTS.md` | 修改 | 2.3 文档处置, 3.2 隐私声明 |
| `README.md` | 修改 | 3.2 隐私声明 |
| `tests/test_rules.py` | 修改 | 2.2 规则补全 |
| `tests/test_probabilistic.py` | **新增** | 3.1 概率推断 |
| `tests/test_multi_user.py` | **新增** | 3.3 多用户 |
| `tests/test_experiment_results.py` | **新增** | 3.4 实验可视化 |
| `tests/test_privacy.py` | **新增** | 3.2 隐私保护 |
| `tests/stores/test_memory_bank_store.py` | 修改 | 2.1 反馈记录 |
| `tests/stores/test_toml_store.py` | 修改 | 3.3 per-user TOMLStore |

**统计**：新增 8 文件，修改 17 文件。比 v1 多 2 新增文件（`config/rules.toml`、`tests/stores/test_toml_store.py`），多 4 修改文件（toml_store、jsonl_store、init_data、config.py）。

---

## 五、约束与假设

1. 时间约束：8 周，第 7-8 周为论文撰写缓冲
2. 技术约束：不加新依赖库（概率推断复用既有 embedding + FAISS；Chart.js CDN 不算依赖）
3. 架构约束：不改工作流节点顺序，不改 FAISS 索引结构
4. 测试约束：所有新功能必须覆盖测试
5. v2 显式放弃向后兼容：数据目录结构从 `data/*.jsonl` 变为 `data/users/{user}/`，需一次性迁移；API `currentUser` 从可选改为必填（`"default"` 等效旧行为）
6. 规则条件表达式限于 TOML 可表达的字段匹配（scenario/workload/fatigue_above/has_passengers），不引入自定义 DSL 或 lambda——当前全集已满足需求
