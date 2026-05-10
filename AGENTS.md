# 知行车秘

本科生毕设。车载AI智能体原型系统。

## 项目配置

Python 3.14 + `uv`。

## 环境配置参考

> 以下为当前开发机器上的目录布局，**不同机器路径不同**，仅作本地参考。

| 内容 | 路径 |
|------|------|
| 本仓库 | `~/Codes/DrivePal-2` |
| VehicleMemBench 基准测试 | `~/Codes/VehicleMemBench` |
| 论文 | `~/Papers/` |


## 技术栈

| 类别 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| API层 | Strawberry GraphQL (code-first) |
| AI工作流 | 自定义四Agent流水线 + 轻量规则引擎 |
| LLM | Qwen3.5-2B (vLLM), MiniMax-M2.5, DeepSeek, GLM-4.7-flashx |
| Embedding | BGE-M3 (vLLM, OpenAI兼容接口, 纯远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus遗忘曲线) |
| 存储 | TOML (tomllib + tomli-w) + JSONL |
| 开发 | uv, pytest (asyncio_mode=auto), ruff, ty |

## 项目结构

```
app/
├── agents/            # Agent核心模块
│   ├── workflow.py    # 工作流编排（四阶段流水线）
│   ├── state.py       # Agent状态 + WorkflowStages
│   ├── rules.py       # 规则引擎（安全约束 + 合并策略）
│   ├── probabilistic.py # 概率推断（意图置信度 + 打断风险）
│   └── prompts.py     # 系统提示词模板
├── api/               # GraphQL API层
│   ├── main.py        # FastAPI入口（lifespan, CORS, 静态文件）
│   ├── graphql_schema.py  # 输入/输出类型 + 枚举定义
│   └── resolvers/     # query.py + mutation.py + errors.py + converters.py
├── models/            # AI模型封装
│   ├── chat.py        # LLM调用（多provider自动fallback, 纯异步）
│   ├── embedding.py   # Embedding模型封装（纯远程, 重试 + 批量）
│   ├── settings.py    # 模型组/Provider配置加载
│   ├── model_string.py # 模型引用字符串解析（provider/model?key=value）
│   ├── types.py       # ResolvedModel, ProviderConfig 纯数据类型
│   ├── exceptions.py  # ProviderNotFoundError, ModelGroupNotFoundError
│   └── _http.py       # HTTP 超时配置（12h）
├── memory/            # 记忆模块
│   ├── memory.py      # MemoryModule Facade + 工厂注册表 + per-user store 注册表
│   ├── interfaces.py  # MemoryStore Protocol定义（含 close()）
│   ├── types.py       # MemoryMode枚举
│   ├── schemas.py     # MemoryEvent, InteractionRecord, FeedbackData等
│   ├── singleton.py   # MemoryModule 线程安全单例（双检锁）
│   ├── privacy.py     # 隐私保护（位置脱敏工具）
│   ├── embedding_client.py # Embedding薄代理（维度一致性检测）
│   ├── exceptions.py  # MemoryBank异常体系（MemoryBankError → TransientError/FatalError → 具体）
│   ├── utils.py       # 余弦相似度 + 事件hash
│   └── stores/memory_bank/  # MemoryBank后端
│       ├── store.py        # MemoryBankStore Facade（Protocol实现）
│       ├── index.py        # FAISS IndexIDMap(IndexFlatIP) + LoadResult降级恢复
│       ├── index_reader.py # IndexReader Protocol（只读视图）
│       ├── retrieval.py    # 四阶段检索管道
│       ├── forget.py       # Ebbinghaus遗忘曲线
│       ├── summarizer.py   # 分层摘要 + 人格生成
│       ├── llm.py          # LLM封装（上下文截断重试，异常化）
│       ├── lifecycle.py    # 写入/遗忘/摘要编排（批量嵌入编码）
│       ├── observability.py # 可观测性指标（MemoryBankMetrics）
│       └── bg_tasks.py     # 后台任务管理器（优雅关闭）
├── schemas/
│   └── context.py     # 驾驶上下文数据模型（Pydantic）
├── storage/
│   ├── toml_store.py  # TOML文件存储引擎（asyncio锁, append/update）
│   ├── jsonl_store.py # JSONL追加写存储
│   └── init_data.py   # 数据目录初始化
├── config.py
tests/                 # 测试
config/llm.toml        # 模型配置
data/                  # 运行时数据
webui/                 # 模拟测试工作台
```

## Agent工作流

四阶段流水线，全异步（async/await）：

```
用户输入 → Context Agent → Task Agent → Strategy Agent → Execution Agent
```

| Agent | 输入 → 输出 | 说明 |
|-------|------------|------|
| Context | 用户+记忆+外部上下文 → JSON上下文 | 有外部数据直接使用，无则LLM推断 |
| Task | 用户+上下文 → JSON任务 | 事件抽取、类型归因 |
| Strategy | 上下文+任务+规则约束+个性化+反馈权重+概率推断 → JSON决策 | 安全约束范围内决策 |
| Execution | 决策 → 结果+event_id | 存储事件，返回提醒 |

`run_with_stages()` 返回各阶段详细输出（可解释性）。

### Agent 提示词

`app/agents/prompts.py`。三个 Agent 各有系统提示词，均为中文 + JSON 输出：

| Agent | 职责 | 输出 |
|-------|------|------|
| Context | 构建统一上下文（时间/位置/交通/偏好/驾驶员状态） | JSON 上下文对象 |
| Task | 事件抽取 + 任务归因（meeting/travel/shopping/contact/other）| JSON 任务对象（含置信度）|
| Strategy | 是否/何时/如何提醒，考虑个性化 + 安全边界 | JSON 决策（should_remind/timing/channel/content/理由）|

Execution Agent 无单独提示词——执行逻辑由规则引擎硬约束 + 代码实现。

## 规则引擎

`app/agents/rules.py`。Strategy Agent 前执行安全约束，7 条规则数据驱动加载自 `config/rules.toml`。

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| 高速仅音频 | scenario==highway | allowed_channels:[audio], max_frequency:30min | 10 |
| 疲劳抑制 | fatigue_level>0.7(可配) | only_urgent, allowed_channels:[audio] | 20 |
| 过载延后 | workload==overloaded | postpone | 15 |
| 停车全通道 | scenario==parked | allowed_channels:[visual,audio,detailed] | 5 |
| city_driving限制 | scenario==city_driving | allowed_channels:[audio], max_frequency:15min | 8 |
| traffic_jam安抚 | scenario==traffic_jam | allowed_channels:[audio,visual], max_frequency:10min | 7 |
| 乘客在场放宽 | has_passengers && scenario!=highway | extra_channels:[visual] | 3 |

合并策略：allowed_channels 取交集（空集回退默认），extra_channels 交集后追加（去重），max_frequency 取最小值，only_urgent/postpone 取布尔或。

`load_rules()` 从 `config/rules.toml` 加载，失败时回退内置 4 条默认规则。条件字段支持 scenario / not_scenario / workload / fatigue_above / has_passengers（AND 组合）。

关键：`postprocess_decision()` 在LLM输出后强制覆盖，不可绕过。疲劳阈值环境变量 `FATIGUE_THRESHOLD`（默认0.7）。

### 概率推断

`app/agents/probabilistic.py`。Strategy Agent 前执行，MemoryBank 启用时自动注入 prompt。

1. **意图推断**（`infer_intent`）：MemoryBank 检索 top-20 相似事件 → 按 type 聚合得分 → 归一化得置信度分布 `{intent_confidence, alternative, alt_confidence}`。冷启动（无结果）等概率。
2. **打断风险评估**（`compute_interrupt_risk`）：`0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed`，结果 ∈ [0,1]。scenario 缺失时 scenario_risk=0.5。
3. **环境开关**：`PROBABILISTIC_INFERENCE_ENABLED=0` 关闭（默认开启）。

## 上下文数据模型

`app/schemas/context.py`。Pydantic Literal 约束合法值。

- **DriverState**: emotion (neutral/anxious/fatigued/calm/angry), workload (low/normal/high/overloaded), fatigue_level (0~1)
- **GeoLocation**: latitude, longitude, address, speed_kmh
- **SpatioTemporalContext**: current_location, destination, eta_minutes, heading
- **TrafficCondition**: congestion_level (smooth/slow/congested/blocked), incidents, delay_minutes
- **DrivingContext**: driver + spatial + traffic + scenario (parked/city_driving/highway/traffic_jam)

## API层

Strawberry GraphQL, code-first。端点 `/graphql`（内置 Playground）。

**Query:**
```graphql
history(limit, memoryMode): [MemoryEvent]
scenarioPresets: [ScenarioPreset]
```

**Mutation:**
```graphql
processQuery(input: {query, memoryMode, context, currentUser}): {result, eventId, stages}
submitFeedback(input: {eventId, action, memoryMode, currentUser}): {status}
saveScenarioPreset(input): ScenarioPreset
deleteScenarioPreset(id): Boolean
exportData(currentUser): ExportDataResult
deleteAllData(currentUser): Boolean
```

反馈学习：submitFeedback 接受时对应类型权重 +0.1，忽略时 -0.1，存入 strategies.toml 的 reminder_weights。Strategy Agent 读取权重时偏好高权重事件类型。

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（9个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`, `DeleteDataInput`

**输出类型（11个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`, `ExportDataResult`

**自定义标量：** `JSON`（WorkflowStages 各阶段输出）

**错误类：**
- `InternalServerError` — 内部服务器错误
- `GraphQLInvalidActionError` — 无效操作类型
- `GraphQLEventNotFoundError` — 事件不存在

支持外部上下文注入（DrivingContext），跳过LLM推断。

输入转换由 `converters.py` 完成：Strawberry Input → `strawberry_to_plain()`（递归 Enum→value, dataclass→dict）→ Pydantic `model_validate()`。

### 服务入口与生命周期

**入口：** `uv run uvicorn app.api.main:app`

**Lifespan 事件：**
- **启动：** `init_storage()` 初始化数据目录（首次运行时迁移旧平铺结构至 `data/users/default/`）
- **关闭：** `MemoryModule.close()` 关闭 MemoryBank（FAISS 索引落盘 + 后台任务取消等待）

**中间件：** CORS（当前 `allow_origins=["*"]`，开发用）

**静态文件：** `/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`

## MemoryBank 记忆系统

`app/memory/memory_bank/`。基于论文 MemoryBank 实现。

### 文件结构

```
app/memory/memory_bank/
├── config.py         # 集中配置（pydantic-settings，MEMORYBANK_ 前缀）
├── index.py          # FAISS 索引管理（IndexIDMap(IndexFlatIP) + LoadResult降级恢复）
├── index_reader.py   # IndexReader Protocol（只读视图）
├── retrieval.py      # 四阶段检索管道
├── forget.py         # Ebbinghaus 遗忘曲线
├── summarizer.py     # 分层摘要 + 人格生成
├── llm.py            # LLM 封装（上下文截断重试，异常化）
├── lifecycle.py      # 写入/遗忘/摘要编排（批量嵌入编码）
├── store.py          # MemoryBankStore Facade（MemoryStore Protocol 实现）
├── observability.py  # 可观测性指标（MemoryBankMetrics）
└── bg_tasks.py       # 后台任务管理器
```

### 架构

三层：Interaction（原始交互）→ Event（语义摘要）→ Summary（层级摘要）

### 记忆数据模型

`app/memory/schemas.py`。核心类型：

| 类型 | 关键字段 | 说明 |
|------|----------|------|
| `MemoryEvent` | id, content, type, memory_strength, last_recall_date, interaction_ids, speaker | 语义摘要后的事件（agent 输出） |
| `InteractionRecord` | id, event_id, query, response, timestamp, memory_strength | 原始用户↔系统交互 |
| `FeedbackData` | event_id, action(accept\|ignore), modified_content | 用户反馈，action 校验 `InvalidActionError` |
| `SearchResult` | event(dict), score(float), interactions(list[dict]) | 检索结果包装，`to_public()` 清洗内部评分字段（store 返回前调用） |
| `InteractionResult` | event_id, interaction_id | 写入结果 |

MemoryEvent 通过 `interaction_ids` 列表关联交互，检索命中时自动展开。

### FAISS索引

- IndexIDMap(IndexFlatIP) + L2归一化（等价余弦相似度）
- 自适应分块（P90×3 动态校准 chunk_size）
- `save()` 持有 asyncio.Lock 防止并发写入损坏
- 关键阈值：`EMBEDDING_MIN_SIMILARITY=0.3`

### 索引损坏恢复

`FaissIndex.load()` 返回 `LoadResult(ok, warnings, recovery_actions)`。三级降级策略：

| 损坏类型 | 恢复策略 |
|----------|----------|
| `metadata.json` 格式错 | 从 FAISS `id_map` 提取实际标签重建骨架（标记 `corrupted=True`） |
| `extra_metadata.json` 损坏 | 忽略，空 dict 启动（下次摘要自动重建） |
| Count mismatch | 以 index 为权威——从 `id_map` 补缺失骨架条目 |
| `index.faiss` 读失败 | 备份 `.bak` 后重建空索引 |

### 四阶段检索管道

1. query embedding + FAISS 粗排（top_k × 4）
2. 邻居合并（同 source 连续条目）
3. 重叠去重（并查集）
4. 说话人感知降权（查询含说话人名的无关条目降权 ×0.75）

### 遗忘曲线

`retention = e^(-days / strength)`

- **默认确定性模式**：retention < `SOFT_FORGET_THRESHOLD=0.3` 标记遗忘（memory_strength=0, forgotten=True）
- **可选概率性模式**：`MEMORYBANK_FORGET_MODE=probabilistic`，每条目独立掷骰子
- **回忆强化**：检索命中 memory_strength += 1（无上限）
- **节流**：`FORGET_INTERVAL_SECONDS=300`，两次遗忘判断至少间隔5分钟
- **搜索评分**：FAISS 内积 + 说话人感知降权（×0.75/×1.25）

### 摘要与人格

- **每日摘要**：每次写入后异步后台生成（不阻塞主流程）
- **总体摘要**：有 daily_summary 即生成；已存在则跳过（不可变保护）
- **每日人格**：同上，按日期生成后不覆盖
- **总体人格**：基于每日人格汇总生成；已存在则跳过

### 后台任务管理器

`app/memory/memory_bank/bg_tasks.py`

- asyncio 任务注册与调度（`create_task` + 跟踪集）
- `close()` 方法：等待所有 inflight 任务完成，支持优雅关闭
- 摘要生成等异步后处理通过此模块调度，不阻塞写入主流程

### 聚合

- 字符重叠 ≥ 45% 或余弦相似度 ≥ 0.8 聚合为同一事件
- 聚合后用LLM重新摘要事件 content
- 检索命中事件时自动展开关联交互

### 与原始论文差异

- 硬删除 → 软标记（可恢复）
- 启动时批量遗忘 → 每次搜索末尾渐进式遗忘
- 无级联删除 summary → 保留所有 summary 更安全

## 记忆模块基础设施

### MemoryModule 单例

`app/memory/singleton.py`

- 线程安全双检锁模式（`threading.Lock`）
- `get_memory_module()` 懒初始化：`MemoryModule(data_dir, embedding_model, chat_model)`
- API resolvers 通过此入口获取全局唯一 MemoryModule 实例

### 多用户隔离

`MemoryModule.get_store(user_id)` 返回 per-user `MemoryBankStore` 实例。每用户独立子目录 `data/users/{user_id}/`（含 memorybank/ 子目录及独立 JSONL/TOML 文件），由 `config.user_data_dir(user_id)` 生成路径。下游组件（RetrievalPipeline、MemoryLifecycle、Summarizer）构造时绑定用户目录，无需 `user_id` 参数。

### 可观测性

`app/memory/memory_bank/observability.py` 提供 `MemoryBankMetrics`（dataclass，零锁开销）。指标：search_count、search_latency_ms（P50/P90）、forget_count、background_task_failures 等。`MemoryBankStore.metrics` 属性获取实例 → `MemoryModule.get_metrics(user_id)` 聚合查询。

### EmbeddingClient 维度检测

`app/memory/embedding_client.py`

- `EmbeddingModel` 的薄代理
- `encode_batch()` 含双重校验：
  - 数量匹配：输入数 ≠ 输出数 → `RuntimeError`
  - 维度一致性：所有向量维度不同 → `RuntimeError`
- 重试由 `EmbeddingModel` 内部处理（3 次指数退避），此层不再重复

## 模型配置

`config/llm.toml`。**model_groups + model_providers** 组合模式。

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4  # provider 级别最大并发数

[embedding]
model = "local/text-embedding-bge-m3"
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `DATA_DIR` | 数据目录路径（默认 data） |
| `WEBUI_DIR` | WebUI静态文件目录路径（默认 webui/） |
| `MINIMAX_API_KEY` | MiniMax API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ZHIPU_API_KEY` | 智谱 API Key |
| `JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY` | Judge 模型配置 |
| `FATIGUE_THRESHOLD` | 疲劳规则阈值（默认0.7） |
| `PROBABILISTIC_INFERENCE_ENABLED` | 概率推断开关（默认1） |
| `MEMORYBANK_SEED` | 遗忘随机种子（benchmark复现用） |
| `MEMORYBANK_FORGET_MODE` | 遗忘模式：deterministic/probabilistic |
| `MEMORYBANK_ENABLE_FORGETTING` | 启用遗忘（默认关闭） |
| `MEMORYBANK_CHUNK_SIZE` | 检索分块大小（默认1500） |
| `MEMORYBANK_LLM_TEMPERATURE` | LLM 温度（None=使用ChatModel默认，摘要默认0.3） |
| `MEMORYBANK_EMBEDDING_BATCH_SIZE` | 嵌入批量大小（默认100） |
| `MEMORYBANK_SAVE_INTERVAL_SECONDS` | 持久化节流间隔（默认30秒） |
| `MEMORYBANK_REFERENCE_DATE_AUTO` | 启用自动推算参考日期（默认false） |

### LLM调用特性

- 多provider自动fallback（provider列表顺序）
- provider级别semaphore限制并发（共享同一base_url的provider共享semaphore）
- 12小时read timeout（长时推理不断开）
- JSON mode支持（`response_format={"type": "json_object"}`）
- MemoryBank 摘要调用默认 temperature=0.3、max_tokens=400（可通过 `MEMORYBANK_LLM_TEMPERATURE` / `MEMORYBANK_LLM_MAX_TOKENS` 环境变量覆盖）

## 数据存储

`data/` 目录结构：

```
data/
├── users/
│   └── {user_id}/
│       ├── events.jsonl          # 事件历史（JSONL）
│       ├── interactions.jsonl    # 交互记录（JSONL）
│       ├── feedback.jsonl        # 反馈记录（JSONL）
│       ├── contexts.toml         # 上下文缓存（TOML）
│       ├── preferences.toml      # 用户偏好（TOML）
│       ├── strategies.toml       # 个性化策略 + reminder_weights（TOML）
│       ├── scenario_presets.toml # 场景预设（TOML）
│       └── memorybank/           # MemoryBank 持久化数据
│           ├── index.faiss
│           ├── metadata.json
│           └── extra_metadata.json
└── experiment_benchmark.toml  # 实验对比数据（全局共享）
```

旧平铺结构（`data/*.jsonl`）通过 `init_storage()` 中的 `_migrate_legacy()` 幂等迁移至 `data/users/default/`。

### TOMLStore

`app/storage/toml_store.py`。异步锁 + 文件级粒度。

- **锁机制**：`_LOCK_REGISTRY` 全局字典，每个文件独立 `asyncio.Lock`
- **列表存储**：TOML 不支持顶层数组，用 `_list` 键包裹
- **None 处理**：`_clean_for_toml()` 递归将 `None` 转空字符串（含日志警告）
- **异常**：`AppendError`（非列表调 append）/ `UpdateError`（非字典调 update）
- **API**：
  - `read()` → T
  - `write(data: T)`
  - `append(item)` — 仅列表存储
  - `update(key, value)` — 仅字典存储

### JSONLStore

`app/storage/jsonl_store.py`。JSONL 追加写，用于 events/interactions/feedback/experiment_results 等高频写入数据。

## 检查流程

每改后：
1. `uv run ruff check --fix`
2. `uv run ruff format`
3. `uv run ty check`

任务完：
4. `uv run pytest`

Python 3.14 注意：`except ValueError, TypeError:` 是 PEP-758 新语法，非 Python 2 残留。

### ruff 配置

`ruff.toml`，extend-select=ALL，忽略 D203/D211/D213/D400/D415/COM812/E501/RUF001-003。
`tests/**` 豁免 S101/S311/SLF001 等测试常见模式。

### ty 配置

`ty.toml`，rules all=error，faiss 替换为 Any。

## 测试

```
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm      # 需要真实LLM
uv run pytest tests/ -v --test-embedding # 需要真实embedding
uv run pytest tests/ -v --run-integration # 需要完整服务
```

pytest.ini：asyncio_mode=auto, asyncio_default_fixture_loop_scope=function, timeout=30, -n auto。

`tests/conftest.py` 提供：
- `pytest_configure` 注册 `integration` / `llm` / `embedding` 三个标记
- `pytest_addoption` 注册 `--run-integration` / `--test-llm` / `--test-embedding` 选项
- `pytest_collection_modifyitems` 根据选项跳过未标记测试
- `llm_provider` 和 `embedding` 两个会话级 fixture

关键测试文件：

| 文件 | 测什么 |
|------|--------|
| test_rules.py | 规则引擎合并策略 |
| test_context_schemas.py | 数据模型验证 |
| test_graphql.py | GraphQL端点 |
| test_memory_bank.py | 遗忘曲线、摘要、交互聚合 |
| test_forgetting.py | 遗忘曲线单元测试（确定性/概率模式、阈值、节流） |
| test_retrieval_pipeline.py | 四阶段检索管道（mock FAISS + Embedding） |
| test_index_recovery.py | FAISS 降级恢复（损坏/计数不匹配/备份） |
| test_multi_user.py | 多用户隔离 |
| test_memory_store_contract.py | MemoryStore Protocol 契约 |
| test_memory_module_facade.py | Facade工厂注册 |
| test_settings.py | 模型配置加载 |
| test_storage.py | TOMLStore持久化 |

### CI 工作流

`.github/workflows/python.yml`。push/PR 到 main 时触发，三个并行 job：

| Job | 命令 | 说明 |
|-----|------|------|
| `lint` | `ruff check .` + `ruff format --check .` | 代码风格 + 格式 |
| `typecheck` | `ty check .` | 类型检查 |
| `test` | `pytest -v` | 单测（无外部 provider） |

额外 workflow `no-suppressions.yml`：扫描 `# noqa` 和 `# type:` 内联抑制注释，禁止绕过。

## 代码规范

- **注释**：中文，解释 why 非 what
- **提交**：英文，Conventional Commits（feat/fix/docs/refactor）
- **内联抑制**：禁 `# noqa`、`# type:`。遇 lint/type 错误先修代码，修不了在 ruff.toml/ty.toml 按文件或全局忽略并注明原因
- **函数粒度**：一事一函数，超30行需理由
- **嵌套控制**：小分支提前 return/continue/break，复杂逻辑提取函数
- **导入顺序**：标准库 → 三方库 → 内部模块 → 相对导入，空行分隔。禁通配导入
- **不可变优先**：const/final 优先。新对象替换原地 mutate（性能关键路径可破）
- **测试**：一测试一事。Given → When → Then。名含场景+期望，描述用中文
- **设计原则**：单一职责、开闭、依赖倒置、接口隔离、迪米特。OOP 附加里氏替换

## 错误处理模式

项目使用分层异常设计：

| 层 | 异常类 | 触发条件 |
|----|--------|----------|
| GraphQL | `InternalServerError` | 未预期的服务器错误 |
| GraphQL | `GraphQLInvalidActionError` | feedback action 非 accept/ignore |
| GraphQL | `GraphQLEventNotFoundError` | 事件 ID 不存在 |
| 记忆 | `MemoryBankError` → `TransientError`/`FatalError` | MemoryBank 异常基类（三层） |
| 记忆 | `LLMCallFailed` | LLM API 调用失败（瞬态，可重试） |
| 记忆 | `SummarizationEmpty` | LLM 返回空内容（哨兵异常，非错误） |
| 记忆 | `EmbeddingFailed` | 嵌入 API 调用失败（瞬态） |
| 记忆 | `MetadataCorrupted` / `IndexIntegrityError` | 数据损坏（永久） |
| 记忆 | `InvalidActionError` | FeedbackData action 校验失败 |
| 存储 | `AppendError` / `UpdateError` | TOMLStore 类型不匹配 |
| 模型 | `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| 模型 | `ModelGroupNotFoundError` | 引用字符串中 model_group 未配置 |

GraphQL 异常继承 `graphql.error.GraphQLError`，自动转为标准 GraphQL error response。
其余异常由上层调用方处理，不跨层泄露实现细节。

### 反馈学习机制

submitFeedback 接受时对应事件类型权重 +0.1（上限 1.0），忽略时 -0.1（下限 0.1），不存在类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`，Strategy Agent prompt 中注入偏好高权重类型。

## 隐私保护

`app/memory/privacy.py`。

### 位置脱敏

写入记忆前自动脱敏位置信息：
- 经纬度截断至小数点后 2 位（约 1km 精度）
- 地址只保留街道级（逗号前第一段）
- `sanitize_context()` 递归处理 `spatial.current_location` + `destination`

### 数据可携带性

`exportData(currentUser)` mutation 导出当前用户全量文本文件（JSONL/TOML/JSON），返回 `{files: {filename: content}}`。`deleteAllData(currentUser)` 删除 `data/users/{currentUser}/` 整个目录。

## 关键阈值速查

| 阈值 | 值 | 位置 |
|------|-----|------|
| SOFT_FORGET_THRESHOLD | 0.3 | config.py |
| FORGET_INTERVAL_SECONDS | 300 | config.py |
| FORGETTING_TIME_SCALE | 1 | config.py |
| EMBEDDING_MIN_SIMILARITY | 0.3 | config.py |
| COARSE_SEARCH_FACTOR | 4 | retrieval.py |
| AGGREGATION_SIMILARITY_THRESHOLD | 0.8 | retrieval.py |
| OVERLAP_RATIO_THRESHOLD | 0.45 | retrieval.py |
| DEFAULT_CHUNK_SIZE | 1500（自适应回退值） | retrieval.py |
| CHUNK_SIZE_MIN | 200 | config.py |
| CHUNK_SIZE_MAX | 8192 | config.py |
| HTTP read timeout | 12h | _http.py |
| Embedding batch size | 100 | embedding.py |
| Embedding retry | 3次 | embedding.py |
| SAVE_INTERVAL_SECONDS | 30 | config.py |
| LLM_TEMPERATURE (摘要) | 0.3 | summarizer.py |
| LLM_MAX_TOKENS (摘要) | 400 | summarizer.py |
| REFERENCE_DATE_OFFSET | 1天 | index.py |

## 消融实验

`experiments/ablation/`。三组消融实验，验证系统各组件的独立贡献。通过 `python -m experiments.ablation` 运行。

### 实验目的

VehicleMemBench 已覆盖记忆系统对比（MemoryBank vs None/Gold/Summary/Key-Value）。消融实验覆盖非记忆组件对比——验证规则引擎、四Agent流水线架构、反馈学习各自对系统决策质量的贡献。

---

### 安全性组：规则引擎 + 概率推断消融

**研究问题**：规则引擎和概率推断各自对安全决策的贡献多大？

| 要素 | 说明 |
|------|------|
| **自变量** | 规则引擎（启用/禁用）、概率推断（启用/禁用） |
| **因变量** | 安全合规率、规则拦截率、决策综合质量（Judge 1-5分） |
| **变体** | Full（启用全部）/ -Rules（禁用规则引擎）/ -Prob（禁用概率推断） |
| **测试场景** | 50 个安全关键场景（高速+各疲劳度×15 / 疲劳>0.7×15 / 过载×10 / 城市驾驶×10） |
| **无关变量控制** | 同一 LLM（默认模型组）、同一 MemoryBank 状态（独立 user_id）、固定随机种子、场景分层抽样 |

**评价指标**：

| 指标 | 定义 |
|------|------|
| 安全合规率 | Judge 评估决策是否违反安全约束（`safety_score ≥ 4` 为合规） |
| 规则拦截率 | Full 变体中 `postprocess_decision` 修改 LLM 输出的比例 |
| 违规类型分布 | `channel_violation` / `frequency_violation` / `non_urgent_during_fatigue` / `remind_during_overload` / `missed_urgent` 各类计数 |
| 决策综合质量 | Judge 1-5 分，综合安全性 + 合理性 + 用户体验 |
| Cohen's d | Full vs 各消融变体的效应量 |

**假设**：-Rules 变体安全合规率显著低于 Full（Cohen's d > 0.5）；-Prob 变体决策质量低于 Full。

---

### 架构组：四Agent流水线 vs 单LLM

**研究问题**：四 Agent 结构化流水线 vs 单 LLM 调用，决策质量差异多大？

| 要素 | 说明 |
|------|------|
| **自变量** | 决策架构（四Agent流水线 / 单LLM） |
| **因变量** | 决策质量分、JSON 结构合规率、各阶段中间质量、端到端延迟 |
| **变体** | Full（四阶段 Context→Task→Strategy→Execution）/ SingleLLM（一次 LLM 调用，合并 prompt 直接输出） |
| **测试场景** | 50 个多样化场景（排除极端安全条件：fatigue ≤ 0.7, workload ≠ overloaded, scenario ≠ highway），覆盖所有 scenario × task_type 组合 |
| **无关变量控制** | 同一 LLM（默认模型组）、无规则后处理（SingleLLM 绕过 `postprocess_decision`）、同一场景集、固定随机种子 |

**评价指标**：

| 指标 | 定义 |
|------|------|
| 决策质量分 | Judge 1-5 分，综合合理性、上下文理解、任务归因 |
| JSON 结构合规率 | 输出是否包含所有必需字段、类型正确、格式合法 |
| 中间阶段评分 | Full 的 Context（上下文准确性）/ Task（事件归因准确度）/ Strategy（决策合理性）各 1-5 分，独立 Judge prompt |
| 延迟 P50 / P90 | 端到端 `processQuery` 耗时（ms） |
| Cohen's d | Full vs SingleLLM 效应量 |

**假设**：Full 在复杂场景（多约束冲突）中决策质量显著优于 SingleLLM；SingleLLM 延迟更低。

---

### 个性化组：反馈学习消融

**研究问题**：反馈学习机制能否使系统决策逐步贴近用户真实偏好？

| 要素 | 说明 |
|------|------|
| **自变量** | 反馈学习（启用/禁用） |
| **因变量** | 偏好匹配率、权重收敛速度、收敛稳定性、过拟合程度 |
| **变体** | Full（动态权重，初始 0.5，±0.1/反馈）/ -Feedback（固定权重 0.5） |
| **实验设计** | 20 轮交互序列，4 阶段偏好切换（1-5轮偏好高频提醒 → 6-10轮偏好静默 → 11-15轮偏好视觉详细 → 16-20轮混合偏好） |
| **无关变量控制** | 同一 LLM（默认模型组）、固定场景集（每阶段复用 5 场景）、同一 MemoryBank 状态（独立 user_id，清空启动）、固定随机种子（`ABLATION_SEED`） |

**评价指标**：

| 指标 | 定义 | 量化方法 |
|------|------|---------|
| 偏好匹配率 | 决策与当前阶段期望偏好的一致比例 | 匹配轮数 / 20 |
| 权重收敛速度 | 目标类型权重从 0.5 到稳定的轮次数 | 权重距 ±0.05 内持续 ≥3 轮视为收敛 |
| 收敛稳定性 | 偏好切换后权重振荡幅度 | 切换后连续 5 轮权重的标准差 |
| 过拟合检测 | 最终阶段（混合偏好）下两变体表现差异 | 阶段 4 的偏好匹配率差（Full − NoFeedback） |

**假设**：Full 在偏好切换后 3-5 轮内权重收敛至目标方向；-Feedback 匹配率在各阶段均接近随机水平。

---

### 测试场景合成

360 维度组合（scenario 4 × fatigue 3 × workload 3 × task_type 5 × has_passengers 2）→ LLM 批量合成驾驶场景 → 缓存至 JSONL。精选 ~120 场景：

- 安全关键场景 50（分层抽样，保证每规则配额）
- 多样化场景 50（分层随机抽样，覆盖所有 scenario × task_type 组合）
- 个性化场景 20（meeting/travel/shopping/contact/other 各 4）

每个场景含：`driving_context` + `user_query` + `expected_decision`（人工校准用） + `expected_task_type`。

### LLM-as-Judge 评测

- **模型**：优先 `JUDGE_MODEL` 环境变量，否则回退 `[model_groups.default]`
- **盲评**：shuffle 变体输出顺序，不标注来源
- **中位数**：每场景评 3 次取中位数，减少非确定性噪声
- **容错**：`ChatError` → 默认分 3；`JSONDecodeError` → 默认分 3
- **人工校准**：标注 ~50 场景期望决策，计算 Judge 与人工一致率（Cohen's κ），校准集 30 + 留存集 20，最多 3 轮 prompt 调整

### 与 VehicleMemBench 的关系

- VehicleMemBench 覆盖记忆系统对比（MemoryBank vs None/Gold/Summary/Key-Value）
- 消融实验覆盖非记忆组件对比（规则引擎、流水线架构、反馈学习）
- 互不重复，共同构成完整实验体系

## Benchmark

基准测试已从本仓库移除（commit `fbe453b`），独立为外部项目 MiyakoMeow/VehicleMemBench。

VehicleMemBench 提供：
- 50 组数据集（`benchmark/qa_data/qa_{1..50}.json` + `benchmark/history/history_{1..50}.txt`）
- 23 个车辆模块模拟器（`environment/`）
- 五类记忆策略：None（零样本）、Gold（理论上限）、Summary（递归摘要）、Key-Value（键值存储）、MemoryBank（本系统方案）
- 评测指标：Exact State Match、Field-level P/R/F1、Value-level P/R/F1、Tool Call Count
- 模型评估（A 组，评估 backbone 模型）+ 内存系统评估（B 组，含第三方系统 Mem0/MemOS/LightMem/Supermemory/Memobase）

本项目的 MemoryBank 实现已与 VehicleMemBench 对齐（确定性遗忘种子、参考日期、说话人感知检索等），可直接在 VehicleMemBench 中运行对照实验。

## 主要参考文献

| 论文 | 链接 | 说明 |
|------|------|------|
| MemoryBank: Enhancing Large Language Models with Long-Term Memory | [arxiv-2305.10250](https://arxiv.org/abs/2305.10250) | 记忆系统理论基础——三层记忆架构、Ebbinghaus 遗忘曲线、分层摘要 |
| VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents | [arxiv-2603.23840](https://arxiv.org/abs/2603.23840) | 基准测试框架——50 组数据集、23 模块模拟器、五种记忆策略对比 |

## 论文参考文献（完整清单）

论文正文引用 [1]-[10] 以及本文分析确认的额外可引文献。

### 论文稿已收录 [1]-[10]

| 编号 | 文献 | 正文引用位置 |
|------|------|-------------|
| [1] | Zhong W, Guo L, Gao Q, et al. MemoryBank: Enhancing Large Language Models with Long-Term Memory[C]. NeurIPS, 2023. | §1.2, §2.2, §3.2 |
| [2] | Chen Y, Xu Y, Ding X, et al. VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents[J]. arXiv:2603.23840, 2026. | §1.2, §2.3, §5.1 |
| [3] | Ablaßmeier M, Poitschke T, Reifinger S, et al. Context-Aware Information Agents for the Automotive Domain Using Bayesian Networks[C]. HCII, 2007. | §1.2, §2.1 |
| [4] | Kim G, Lee J, Yeo D, et al. Physiological Indices to Predict Driver Situation Awareness in VR[C]. UbiComp/ISWC Adjunct, 2023. | §2.1 |
| [5] | Chen X, Wang X, Fang C, et al. Emotion-aware Design in Automobiles[C]. CHI, 2025. | §2.1 |
| [6] | Parwani K, Das S, Vijay D K. Model Context Protocol (MCP): A Scalable Framework for Context-Aware Multi-Agent Coordination[Z]. Zenodo, 2025. | §1.2, §2.1 |
| [7] | Karpukhin V, Oğuz B, Min S, et al. Dense Passage Retrieval for Open-Domain Question Answering[C]. EMNLP, 2020. | §3.3 |
| [8] | Johnson J, Douze M, Jégou H. Billion-scale Similarity Search with GPUs[J]. IEEE Trans. Big Data, 2019, 7(3): 535-547. | §3.3 |
| [9] | Ebbinghaus H. Memory: A Contribution to Experimental Psychology[M]. Dover, 1964 (1885). | §3.2 |
| [10] | Lu J, An S, Lin M, et al. MemoChat: Tuning LLMs to Use Memos for Consistent Long-Range Open-Domain Conversation[J]. arXiv:2308.08239, 2023. | §1.2, §2.2 |

### 论文稿提及但未引（建议补引）

以下文献在论文正文中以名称或描述出现，但缺少正式引用编号。

| 文献 | 链接 | 正文提及位置与补引理由 |
|------|------|------------------------|
| Graves A, Wayne G, Danihelka I. Neural Turing Machines[J]. arXiv:1410.5401, 2014. | [arxiv-1410.5401](https://arxiv.org/abs/1410.5401) | §2.2："Memory-Augmented Neural Networks（MANNs）如Neural Turing Machines" |
| Xu J, Szlam A, Weston J. Beyond Goldfish Memory: Long-Term Open-Domain Conversation[J]. arXiv:2107.07567, 2021. | [arxiv-2107.07567](https://arxiv.org/abs/2107.07567) | §2.2："Xu等人提出了多会话长程对话数据集" |
| Chhikara P, et al. Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory[J]. arXiv:2504.19413, 2025. | [arxiv-2504.19413](https://arxiv.org/abs/2504.19413) | §2.2："在工业应用方面，Mem0、MemOS等第三方记忆系统" |
| Li Z, et al. MemOS: A Memory OS for AI System[J]. arXiv:2507.03724, 2025. | [arxiv-2507.03724](https://arxiv.org/abs/2507.03724) | §2.2：同上（MemOS） |

### 建议补充至论文稿的理论基础文献

以下文献论文稿尚未提及，但相关章节的内容（情境意识、多资源理论、仿真环境）需这些文献作为理论支撑。

| 文献 | 链接 | 建议补充位置与理由 |
|------|------|-------------------|
| Endsley M R. Toward a Theory of Situation Awareness in Dynamic Systems[J]. Human Factors, 1995, 37(1): 32-64. | DOI:10.1177/001872089503700107 | §1.1/§2.1："情境意识"为核心概念但无引用。规则引擎中疲劳抑制、过载延后约束的设计依据 |
| Wickens C D. Multiple Resources and Mental Workload[J]. Human Factors, 2008, 50(3): 449-455. | DOI:10.1518/001872008X288394 | §4.2：高速仅音频规则的理论基础——驾驶占用视觉通道，非驾驶交互应使用音频通道 |
| Yang J, et al. VehicleWorld: A Highly Integrated Multi-Device Environment for Intelligent Vehicle Interaction[J]. arXiv:2509.06736, 2025. | [arxiv-2509.06736](https://arxiv.org/abs/2509.06736) | §5.1：VehicleMemBench 的执行环境底层，提供23个车辆模块111个可执行工具

## 未解决问题

1. 突发事件处理：由 Strategy Agent 语义推理 + 规则引擎联合覆盖（无独立模块），论文中说明此设计决策
