# 开发指南

## 配置说明

### 模型配置 (`config/llm.toml`)

所有 LLM、Embedding 模型配置统一在 `config/llm.toml` 管理，Python 侧由 `app/models/settings.py` 加载（`LLMSettings.load()`）。配置采用 **model_groups + model_providers** 组合模式：

- **model_providers**：定义 provider（`base_url`/`api_key`/`api_key_env`），如 `local`、`minimax-cn`、`deepseek`
- **model_groups**：通过 `"provider/model?params"` 字符串引用 provider，如 `default`、`benchmark`、`smart`、`fast`、`balanced`

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_groups.benchmark]
models = ["local/qwen3.5-2b?temperature=0.0&max_tokens=8192"]

[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4  # provider 级别最大并发数

[model_providers.minimax-cn]
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"
concurrency = 4

[embedding]
model = "local/text-embedding-bge-m3"
```

**Provider 并发控制：**
- `concurrency`：每个 provider 的最大并发请求数（默认 4），使用 semaphore 实现
- 当同一 provider 被多个 model_groups 引用时，共享同一个 semaphore

**Judge 模型配置：**

可选配置独立的 judge 评估模型（用于 benchmark 评估），支持配置文件或环境变量：

```toml
[judge]
model = "local/qwen3.5-2b"
temperature = 0.1
```

环境变量覆盖：`JUDGE_MODEL`、`JUDGE_BASE_URL`、`JUDGE_API_KEY`、`JUDGE_TEMPERATURE`

**HTTP 客户端超时：**
- `app/models/_http.py` 统一配置所有 LLM/Embedding HTTP 客户端超时
- read timeout 设为 12 小时，避免长时推理任务中途断开
- connect timeout 10 秒，快速发现连接问题

**环境变量覆盖：**

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 `config/llm.toml`） |
| `DATA_DIR` | 数据目录路径（默认 `data`），服务启动时自动初始化 |
| `WEBUI_DIR` | WebUI 静态文件目录路径（默认项目根目录下 `webui/`） |
| `MINIMAX_API_KEY` | MiniMax provider API Key（用于 `balanced` 模型组） |
| `DEEPSEEK_API_KEY` | DeepSeek provider API Key（用于 `smart` 模型组） |
| `ZHIPU_API_KEY` | 智谱 provider API Key（用于 `fast` 模型组） |
| `JUDGE_MODEL` | Judge 评估模型（如 `local/qwen3.5-2b`） |
| `BENCHMARK_QUERY_CONCURRENCY` | Benchmark 评估查询并发数（默认 `4`） |
| `BENCHMARK_SEARCH_TIMEOUT` | Benchmark memory_bank 搜索超时秒数（默认 `43200`） |

---

## API 层

### GraphQL API (`/graphql`)

系统使用 Strawberry GraphQL（code-first）作为唯一 API 层。Schema 定义在 `app/api/graphql_schema.py`，resolvers 在 `app/api/resolvers/`。

**添加新字段：**
1. 在 `graphql_schema.py` 中定义 Strawberry type/input
2. 在 `resolvers/query.py` 或 `resolvers/mutation.py` 中添加 resolver 方法

**GraphQL Playground：** 启动服务后访问 `/graphql`，自动提供交互式查询界面。

---

## 驾驶上下文数据模型

定义在 `app/schemas/context.py`，所有字段通过 Pydantic Literal 约束合法值：

| 模型 | 字段 | 类型 | 说明 |
|------|------|------|------|
| `DriverState` | `emotion` | `Literal["neutral", "anxious", "fatigued", "calm", "angry"]` | 驾驶员情绪 |
| | `workload` | `Literal["low", "normal", "high", "overloaded"]` | 工作负荷 |
| | `fatigue_level` | `float` (0~1) | 疲劳等级 |
| `GeoLocation` | `latitude` / `longitude` | `float` | 经纬度（含边界校验） |
| | `address` / `speed_kmh` | `str` / `float` | 地址、车速 |
| `SpatioTemporalContext` | `current_location` / `destination` | `GeoLocation` | 当前位置 / 目的地 |
| | `eta_minutes` / `heading` | `float?` | ETA / 航向 |
| `TrafficCondition` | `congestion_level` | `Literal["smooth", "slow", "congested", "blocked"]` | 拥堵等级 |
| | `incidents` / `estimated_delay_minutes` | `list[str]` / `int` | 事故列表 / 延误 |
| `DrivingContext` | `driver` / `spatial` / `traffic` | 子模型 | 完整上下文 |
| | `scenario` | `Literal["parked", "city_driving", "highway", "traffic_jam"]` | 驾驶场景 |
| `ScenarioPreset` | `id` / `name` / `context` / `created_at` | — | 场景预设（自动生成 ID 和时间戳） |

---

## 规则引擎

定义在 `app/agents/rules.py`，在 Strategy Agent 之前应用安全约束。

**添加新规则：**
```python
SAFETY_RULES.append(Rule(
    name="rule_name",
    condition=lambda ctx: ctx["scenario"] == "some_scenario",
    constraint={"allowed_channels": ["audio"]},
    priority=10,
))
```

**合并策略：** 多规则匹配时按优先级从高到低处理，`allowed_channels` 取交集（空集时回退到最低优先级规则的值），`only_urgent` / `postpone` 取布尔或。

---

## 数据存储

### 存储目录结构

```
data/
├── events.toml               # 事件历史（含 interaction_ids）
├── interactions.toml         # 原始交互记录
├── memorybank_summaries.toml # MemoryBank 层级摘要
│   ├── daily_summaries: {}   # {date → {content, memory_strength, event_count}}
│   └── overall_summary: ""   # 总摘要
├── memorybank_personality.toml # MemoryBank 个性分析（运行时自动初始化）
├── contexts.toml            # 上下文缓存
├── preferences.toml         # 用户偏好
├── feedback.toml            # 用户反馈记录
├── strategies.toml          # 个性化策略
├── experiment_results.toml   # 实验结果
└── scenario_presets.toml    # 模拟场景预设
```

### 存储接口 (`app/storage/toml_store.py`)

```python
store = TOMLStore(data_dir, Path("filename.toml"), dict)

store.read()           # 读取数据
store.write(data)      # 写入数据
store.append(item)     # 追加单项（仅list类型）
store.update(key, val) # 更新键值（仅dict类型）
```

**运行时自动初始化的文件**：

以下文件不在 `init_data.py` 预创建，由 `TOMLStore` 在首次读取时自动生成：
- `memorybank_personality.toml`：首次读取时自动创建 `{"daily_personality": {}, "overall_personality": ""}`

---

## 测试

### 运行所有测试

```bash
uv run pytest tests/ -v
```

### 运行需要外部服务的测试

测试通过 marker 控制跳过逻辑，默认跳过所有需要外部服务的测试：

```bash
# 运行需要 LLM provider 的测试
uv run pytest tests/ -v --test-llm

# 运行需要 embedding provider 的测试
uv run pytest tests/ -v --test-embedding

# 运行集成测试（GraphQL 端到端，需要完整服务）
uv run pytest tests/ -v --run-integration

# 组合使用
uv run pytest tests/ -v --test-llm --test-embedding
```

| 标志 | marker | 说明 |
|------|--------|------|
| `--test-llm` | `@pytest.mark.llm` | 需要真实 LLM provider 的测试 |
| `--test-embedding` | `@pytest.mark.embedding` | 需要真实 embedding provider 的测试 |
| `--run-integration` | `@pytest.mark.integration` | 需要完整服务的集成测试 |

### 测试覆盖模块

| 文件 | 说明 |
|------|------|
| `tests/test_benchmark/test_common.py` | 适配器通用工具函数 |
| `tests/test_benchmark/test_model_config.py` | 模型字符串解析 |
| `tests/test_benchmark/test_runner.py` | VehicleMemBench 运行器 |
| `tests/test_benchmark/test_reporter_md.py` | 结果收集与 Markdown 报告生成 |
| `tests/test_benchmark/test_strategies.py` | 记忆策略注册表与接口 |
| `tests/stores/test_memory_bank_store.py` | MemoryBank 后端 |
| `tests/test_context_schemas.py` | 驾驶上下文数据模型 |
| `tests/test_graphql.py` | GraphQL 端点测试 |
| `tests/test_rules.py` | 规则引擎测试 |
| `tests/test_chat.py` | Chat 驱动 LLM 多provider fallback、Workflow 上下文注入 |
| `tests/test_embedding.py` | Embedding 远程接口语义检索与聚合 |
| `tests/test_memory_bank.py` | 遗忘曲线、层级摘要、交互聚合 |
| `tests/test_storage.py` | TOMLStore 跨实例持久化、反馈策略更新 |
| `tests/test_settings.py` | 模型配置加载与 model_groups 解析 |
| `tests/test_components.py` | 可组合组件 |
| `tests/test_memory_module_facade.py` | MemoryModule Facade 工厂注册 |
| `tests/test_memory_store_contract.py` | MemoryStore Protocol 契约测试 |
| `tests/test_memory_types.py` | MemoryMode 枚举 |
| `tests/test_schemas.py` | 数据模型验证 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web框架** | FastAPI + Uvicorn |
| **API 层** | Strawberry GraphQL (code-first) |
| **AI工作流** | 自定义四阶段 Agent 流水线 + 轻量规则引擎 |
| **LLM支持** | Qwen3.5-2B (vLLM, 默认), MiniMax-M2.5, DeepSeek-chat, GLM-4.7-flashx |
| **LLM推理** | vLLM (本地部署), OpenAI兼容接口（多provider自动fallback，纯异步客户端） |
| **嵌入模型** | BGE-M3 (vLLM 部署, OpenAI 兼容接口，纯远程无本地计算依赖) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线+分层摘要+个性分析) |
| **数据存储** | TOML文件 (tomllib + tomli-w) |
| **数据集** | HuggingFace Datasets |
| **基准测试** | VehicleMemBench (vendor 子模块) |
| **开发工具** | uv (包管理), pytest (测试, asyncio_mode=auto), ruff (lint, 扩展规则集), ty (类型检查) |

---

## MemoryBank 实现差异分析

基于 [MemoryBank-SiliconFriend](https://github.com/zhongwanjun/MemoryBank-SiliconFriend)（论文 [MemoryBank: Enhancing Large Language Models with Long-Term Memory](https://arxiv.org/pdf/2305.10250.pdf)）原始仓库的逐行对比。

### 一、遗忘机制

#### 1.1 遗忘触发时机与方式（根本性差异）

| 维度 | 原始仓库 | 本项目 |
|------|---------|--------|
| **触发点** | 会话启动时一次性批量处理（`MemoryForgetterLoader.initial_load_forget_and_save`） | 每次搜索时逐次处理（`MemoryBankEngine._strengthen_and_forget`） |
| **遗忘方式** | 概率性随机（`random.random() > retention_probability` 即删除） | 确定性阈值（`retention < SOFT_FORGET_THRESHOLD` 即标记） |
| **遗忘结果** | 硬删除——从数组中 `.pop()`，甚至级联删除 summary | 软标记——`memory_strength = 0` + `forgotten = True` |

**原始仓库**（[forget_memory.py:115-131](https://github.com/zhongwanjun/MemoryBank-SiliconFriend/blob/main/memory_bank/memory_retrieval/forget_memory.py#L115)）：对每条记忆独立掷骰子（`random.random() > retention_probability`），未通过的记忆从数组中 `.pop()` 硬删除；若该日所有对话均被遗忘，则级联删除对应 summary。

**本项目**（`app/memory/stores/memory_bank/engine.py:257-274`）：遍历所有事件，命中检索的强化（`strength += 1`），未命中的计算 retention，低于 `SOFT_FORGET_THRESHOLD=0.15` 时设置 `memory_strength = 0` + `forgotten = True`，仅标记不删除。

**差异分析**：

- 原始的随机遗忘更接近论文语义——Ebbinghaus 遗忘曲线描述的是记忆保持的**概率**，同一记忆在不同时刻可能存活也可能遗忘，具有不可预测性。本项目的确定性阈值使相同 `strength + days_elapsed` 总是产生相同结果，丧失了随机性。
- 原始在启动时遗忘、运行期间不遗忘；本项目在每次搜索时遗忘——渐进式遗忘 vs 批量遗忘。
- 原始的硬删除 + 连带删除 summary 是级联的；本项目没有级联逻辑。

**评估**：确定性软遗忘在工程上更安全（可恢复），但损失了论文核心卖点"模拟人类随机遗忘"。如需精确复现论文语义，可引入概率性遗忘选项。

#### 1.2 Summary 的遗忘处理

**原始仓库**：summary 条目也参与遗忘曲线，拥有独立的 `memory_strength` 和 `last_recall_date`（`forget_memory.py:138-146`），同样进入向量索引。此外 summary 会被**连带删除**——该日所有对话被遗忘时 summary 也被移除。

**本项目**：summary 通过 `strengthen_summaries` 有独立强化逻辑，但**没有遗忘逻辑**——summary 永远不会被遗忘，记忆强度仅影响搜索排序分数。

**评估**：保留所有 summary 是更安全的工程选择，summary 是高度压缩信息，遗忘 summary 会丢失大量上下文。

---

### 二、检索机制

#### 2.1 向量索引架构

| 维度 | 原始仓库 | 本项目 |
|------|---------|--------|
| **索引类型** | FAISS（ANN）或 LlamaIndex | 无索引，全量遍历 + 余弦相似度 |
| **搜索算法** | FAISS 近似最近邻，O(log n) | 暴力搜索，O(n) |
| **文档分块** | ChineseTextSplitter + 按 source 聚合相邻块 | 无分块，每事件独立检索单元 |
| **top_k** | 默认 6 | 默认 3（搜索接口默认 10） |

**原始仓库的关键特性——相邻块聚合**（`forget_memory.py:187-230`）：

原始仓库重写了 FAISS 的 `similarity_search_with_score_by_vector`，在返回 top-k 结果后向两侧扩展相同 `source`（日期）的相邻块，直到总长度超过 `CHUNK_SIZE`（200 字符），保证同一日期的片段被拼接返回。本项目以单条事件为单位存储，天然不需要分块与拼接。

**评估**：对当前规模（单用户、车载场景）全量遍历足够。未来扩展到大规模记忆时再引入 FAISS。

#### 2.2 搜索评分公式（改进）

**原始仓库**：搜索分数仅来自 FAISS 向量距离，遗忘曲线不参与搜索评分——仅在加载时决定是否保留到索引中（二值效应）。

**本项目**（`engine.py:226`）：搜索分数 = `similarity * retention`，遗忘曲线成为连续权重——被强化过的记忆排名更高，长期未被回忆的记忆排名更低。这是有意的设计改进，更符合"记忆逐渐模糊"的直觉。

#### 2.3 关键词搜索回退（新增）

**原始仓库**：无回退机制，FAISS 不可用则直接失败。

**本项目**（`engine.py:102-107`）：embedding 搜索无结果时自动回退到关键词搜索。纯工程改进。

---

### 三、摘要机制

#### 3.1 触发条件与不可变性

| 维度 | 原始仓库 | 本项目 |
|------|---------|--------|
| **每日摘要触发** | 手动/批量——`summarize_memory()` 由用户主动调用，遍历所有未摘要日期 | 自动/增量——每次写入事件时检查，达阈值 2 条事件触发 |
| **总体摘要触发** | 每次运行时无条件重新生成 | 仅当 `daily_summaries` 数量 ≥ 3 且有新增时触发 |
| **摘要不可变性** | 无保护——每次运行覆盖已有摘要 | 有保护——检查 `isinstance(dict)` 跳过已生成条目 + `_inflight` 防并发 |

**评估**：本项目的增量触发 + 不可变性 + 并发保护是显著的工程改进，避免了重复 LLM 调用和竞态条件。

#### 3.2 摘要输入来源差异

**原始仓库**（`summarize_memory.py:67-77`）：使用**原始对话文本**（完整的 query + response 对）。

**本项目**（`summarization.py:169-171`）：使用**事件的 `content` 字段**。对于通过 `write_interaction()` 写入的事件，`content` 可能已被 `_update_event_summary` 摘要过（`engine.py:411`），存在"对摘要做摘要"的精度损失风险。

**改进建议**：生成每日摘要时优先使用 `interactions` 中的原始 query/response，确保摘要输入是原始对话。

---

### 四、人格分析

#### 4.1 人格摘要的遗忘曲线（增强）

| 阈值 | 值 | 说明 |
|------|-----|------|
| `PERSONALITY_SUMMARY_THRESHOLD` | 2 | 每日个性摘要触发所需事件数 |
| `OVERALL_PERSONALITY_THRESHOLD` | 3 | 生成总体个性画像所需日摘要数 |

**原始仓库**：`personality` 字段是纯文本，没有 `memory_strength`，不参与遗忘曲线。

**本项目**（`personality.py:56-61`）：personality 条目拥有 `memory_strength` 和 `last_recall_date`，搜索时受遗忘曲线影响（`score = retention * SUMMARY_WEIGHT * 0.8`），且被检索命中时会强化。

**评估**：本项目的做法更合理。原始仓库中 personality 不受遗忘影响是设计遗漏——人格特质应随时间淡化（人会改变）。额外的 `SUMMARY_WEIGHT * 0.8` 降权使人格搜索结果排名低于事件，语义合理。

#### 4.2 总体人格的生成策略

**原始仓库**：每次运行 `summarize_memory()` 时无条件重新生成 `overall_personality`。

**本项目**（`personality.py:136-220`）：仅在 `daily_personality` 数量 ≥ `OVERALL_PERSONALITY_THRESHOLD=3` 且有新增条目时触发，带并发保护（snapshot count 校验，防止生成期间数据变更导致覆盖丢失）。

#### 4.3 关键阈值

| 阈值 | 值 | 位置 |
|------|-----|------|
| `PERSONALITY_SUMMARY_THRESHOLD` | 2 | 每日个性摘要触发所需事件数 |
| `OVERALL_PERSONALITY_THRESHOLD` | 3 | 生成总体个性画像所需日摘要数 |

---

### 五、交互记录与事件聚合（新增能力）

**原始仓库**：对话以扁平结构存储在 `history[date] = [{query, response}]` 中，每条对话独立记忆。

**本项目**：引入 Event + Interaction 两级模型——多个语义相近的交互可聚合为同一事件：

- `_should_append_to_event`（`engine.py:366-389`）：基于余弦相似度 ≥ 0.8 或字符重叠 ≥ 50% 判定
- `_update_event_summary`（`engine.py:391-414`）：聚合后用 LLM 重新摘要事件 content
- 检索命中事件时，自动附加其关联的所有原始交互记录（`_expand_event_interactions`）

**评估**：这是最大的架构改进。原始仓库中同一主题的多次对话分散存储，检索时需多次匹配才能拼凑完整上下文。事件聚合将相关交互归组，一次命中即可带回完整上下文。

---

### 六、未实现部分的价值评估

| 原始仓库特性 | 实现价值 | 说明 |
|-------------|---------|------|
| **概率性随机遗忘** | 中 | 论文语义还原的关键特性，建议作为可选参数实现（`ForgetStrategy.PROBABILISTIC`） |
| **FAISS 向量索引** | 低（当前） | 单用户车载场景全量遍历足够，未来大规模记忆时再引入 |
| **LlamaIndex 路径** | 无 | 与 FAISS 功能重复，无需额外依赖 |
| **多用户隔离** | 视需求 | 车载单驾驶员场景不需要，家庭用车/多驾驶员时再添加 |
| **Summary 连带遗忘** | 低 | 保留 summary 更安全，级联删除的收益有限 |
| **双语 Prompt 模板** | 低 | 当前场景中文足够 |
| **相邻块聚合检索** | 低 | 本项目以单条事件为检索单元，不需要分块拼接 |

---

### 七、改进建议优先级

| 优先级 | 改进项 | 理由 |
|--------|--------|------|
| 中 | 概率性遗忘选项 | 论文语义还原，benchmark 可复现性 |
| 中 | 摘要输入使用原始对话 | 避免对摘要做摘要的精度损失 |
| 低 | FAISS 向量索引 | 当前规模不需要 |
| 低 | 多用户隔离 | 视产品需求 |
