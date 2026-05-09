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
| Strategy | 上下文+任务+规则约束+个性化 → JSON决策 | 安全约束范围内决策 |
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

`app/agents/rules.py`。Strategy Agent 前执行安全约束。

| 规则 | 条件 | 约束 |
|------|------|------|
| 高速仅音频 | scenario==highway | allowed_channels:[audio], max_frequency:30min |
| 疲劳抑制 | fatigue_level>0.7(可配) | only_urgent, allowed_channels:[audio] |
| 过载延后 | workload==overloaded | postpone |
| 停车全通道 | scenario==parked | allowed_channels:[visual,audio,detailed] |

合并策略：优先级排序，allowed_channels 取交集（空集回退默认），only_urgent/postpone 取布尔或。

关键：`postprocess_decision()` 在LLM输出后强制覆盖，不可绕过。疲劳阈值环境变量 `FATIGUE_THRESHOLD`（默认0.7）。

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
processQuery(input: {query, memoryMode, context}): {result, eventId, stages}
submitFeedback(input: {eventId, action, memoryMode}): {status}
saveScenarioPreset(input): ScenarioPreset
deleteScenarioPreset(id): Boolean
```

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（8个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`

**输出类型（10个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`

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
- **启动：** `init_storage(DATA_DIR)` 初始化数据目录和文件
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

`MemoryModule.get_store(user_id)` 返回 per-user `MemoryBankStore` 实例。每用户独立子目录 `data/memorybank/user_{user_id}/`，含独立 FAISS 索引、metadata、extra_metadata。下游组件（RetrievalPipeline、MemoryLifecycle、Summarizer）无需 `user_id` 参数——构造时绑定用户。

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
├── events.jsonl          # 事件历史（JSONL）
├── interactions.jsonl    # 交互记录（JSONL）
├── feedback.jsonl        # 反馈记录（JSONL）
├── experiment_results.jsonl # 实验结果（JSONL）
├── contexts.toml         # 上下文缓存（TOML）
├── preferences.toml      # 用户偏好（TOML）
├── strategies.toml       # 个性化策略（TOML）
├── scenario_presets.toml # 场景预设（TOML）
└── memorybank/
    └── user_{user_id}/   # 每用户独立子目录（多用户隔离）
        ├── index.faiss       # FAISS向量索引
        ├── metadata.json     # 事件元数据
        └── extra_metadata.json  # 额外元数据（summary/personality）
```

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

## 未解决问题

1. 反馈学习：已实现——反馈记录到 feedback.jsonl，权重更新在 submit_feedback resolver 中（accept +0.1 / ignore -0.1，限幅 [0.1, 1.0]，初始 0.5）
2. 多用户隔离：已实现——全栈 per-user 目录（`data/users/{user_id}/`），含 MemoryBank 子目录 + 独立 JSONL/TOML 文件
3. 规则引擎：已补全至 7 条（含 city_driving/traffic_jam/乘客在场），数据驱动加载自 `config/rules.toml`
4. 概率推断：已实现——嵌入向量相似度意图推断 + 打断风险加权公式，环境变量开关
5. 隐私保护：已实现——位置脱敏工具 `app/memory/privacy.py` + `exportData`/`deleteAllData` GraphQL mutation
6. 突发事件处理：由 Strategy Agent 语义推理 + 规则引擎联合覆盖（无独立模块），论文中说明此设计决策
