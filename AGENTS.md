# 知行车秘

本科生毕设。车载AI智能体原型系统。

## 项目配置

Python 3.14 + `uv`。NixOS 下运行异常则 `nix develop --command` 包裹。

## 技术栈

| 类别 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| API层 | Strawberry GraphQL (code-first) |
| AI工作流 | 自定义四Agent流水线 + 轻量规则引擎 |
| LLM | Qwen3.5-2B (vLLM), MiniMax-M2.5, DeepSeek, GLM-4.7-flashx |
| Embedding | BGE-M3 (vLLM, OpenAI兼容接口, 纯远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus遗忘曲线) |
| 存储 | TOML文件 (tomllib + tomli-w) |
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
│   ├── main.py        # FastAPI入口
│   ├── graphql_schema.py
│   └── resolvers/     # query.py + mutation.py + _helpers.py
├── models/            # AI模型封装
│   ├── chat.py        # LLM调用（多provider自动fallback, 纯异步）
│   ├── embedding.py   # Embedding模型封装（纯远程, 重试 + 批量）
│   ├── settings.py    # 模型组/Provider配置加载
│   └── model_string.py
├── memory/            # 记忆模块
│   ├── memory.py      # MemoryModule Facade + 工厂注册表
│   ├── interfaces.py  # MemoryStore Protocol定义
│   ├── types.py       # MemoryMode枚举
│   ├── schemas.py     # MemoryEvent, InteractionRecord等
│   └── memory_bank/         # MemoryBank后端
│       ├── store.py        # MemoryStore实现
│       ├── faiss_index.py  # FAISS IndexIDMap(IndexFlatIP)
│       ├── retrieval.py    # 四阶段检索管道
│       ├── forget.py       # Ebbinghaus遗忘曲线
│       ├── summarizer.py   # 分层摘要 + 人格生成
│       └── llm.py          # LLM封装（上下文截断重试）
├── schemas/
│   └── context.py     # 驾驶上下文数据模型
├── storage/
│   ├── toml_store.py  # TOML文件存储引擎
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

支持外部上下文注入（DrivingContext），跳过LLM推断。

## MemoryBank 记忆系统

`app/memory/memory_bank/`。基于论文 MemoryBank 实现。

### 架构

三层：Interaction（原始交互）→ Event（语义摘要）→ Summary（层级摘要）

### FAISS索引

- IndexIDMap(IndexFlatIP) + L2归一化（等价余弦相似度）
- 每日检索时重建索引，确保数据新鲜
- 自适应分块（P90×3 动态校准 chunk_size）
- 关键阈值：`EMBEDDING_MIN_SIMILARITY=0.3`, `SUMMARY_WEIGHT=0.8`

### 四阶段检索管道

1. query embedding + FAISS 粗排（top_k × 4）
2. 邻居合并（同 source 连续条目）
3. 重叠去重（并查集）
4. 说话人感知降权（查询含说话人名的结果加分）

### 遗忘曲线

`retention = e^(-days / (5 × strength))`

- **默认确定性模式**：retention < `SOFT_FORGET_THRESHOLD=0.15` 标记遗忘（memory_strength=0, forgotten=True）
- **可选概率性模式**：`MEMORYBANK_FORGET_MODE=probabilistic`，每条目独立掷骰子
- **回忆强化**：检索命中 memory_strength += 1（无上限）
- **节流**：`FORGET_INTERVAL_SECONDS=300`，两次遗忘判断至少间隔5分钟
- **搜索评分**：`score = similarity × retention`（遗忘曲线为连续权重）
- 额外：名称匹配加分（×1.3），时效性衰减（最低0.7）

### 摘要与人格

- **每日摘要**：事件数达阈值触发，自动/增量
- **总体摘要**：daily_summaries ≥ 3且有新增时触发
- **不可变性保护**：已生成条目不覆盖 + _inflight防并发
- 人格(persionality)也参与遗忘曲线，权重降为 SUMMARY_WEIGHT × 0.8

### 聚合

- 字符重叠 ≥ 45% 或余弦相似度 ≥ 0.8 聚合为同一事件
- 聚合后用LLM重新摘要事件 content
- 检索命中事件时自动展开关联交互

### 与原始论文差异

- 硬删除 → 软标记（可恢复）
- 启动时批量遗忘 → 每次搜索末尾渐进式遗忘
- 无级联删除 summary → 保留所有 summary 更安全

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

### LLM调用特性

- 多provider自动fallback（provider列表顺序）
- provider级别semaphore限制并发（共享同一base_url的provider共享semaphore）
- 12小时read timeout（长时推理不断开）
- JSON mode支持（`response_format={"type": "json_object"}`）

## 数据存储

`data/` 目录结构：

```
data/
├── events.toml           # 事件历史
├── contexts.toml         # 上下文缓存
├── preferences.toml      # 用户偏好
├── feedback.toml         # 反馈记录
├── strategies.toml       # 个性化策略
├── experiment_results.toml
├── scenario_presets.toml
└── memorybank/
    ├── index.faiss       # FAISS向量索引
    ├── metadata.json     # 事件元数据
    └── extra_metadata.json  # 额外元数据（summary/personality）
```

TOMLStore：异步锁 + 文件级粒度（每个文件独立锁），支持 read/write/append/update。

测试用 JSONLStore：`app/storage/jsonl_store.py`。

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

pytest.ini：asyncio_mode=auto, timeout=30, -n auto。

关键测试文件：

| 文件 | 测什么 |
|------|--------|
| test_rules.py | 规则引擎合并策略 |
| test_context_schemas.py | 数据模型验证 |
| test_graphql.py | GraphQL端点 |
| test_memory_bank.py | 遗忘曲线、摘要、交互聚合 |
| test_memory_store_contract.py | MemoryStore Protocol 契约 |
| test_memory_module_facade.py | Facade工厂注册 |
| test_settings.py | 模型配置加载 |
| test_storage.py | TOMLStore持久化 |

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

## 关键阈值速查

| 阈值 | 值 | 位置 |
|------|-----|------|
| SOFT_FORGET_THRESHOLD | 0.15 | forget.py |
| FORGET_INTERVAL_SECONDS | 300 | forget.py |
| FORGETTING_TIME_SCALE | 1 | forget.py |
| EMBEDDING_MIN_SIMILARITY | 0.3 | faiss_index.py |
| COARSE_SEARCH_FACTOR | 4 | retrieval.py |
| AGGREGATION_SIMILARITY_THRESHOLD | 0.8 | retrieval.py |
| OVERLAP_RATIO_THRESHOLD | 0.45 | retrieval.py |
| SUMMARY_WEIGHT | 0.8 | retrieval.py |
| NAME_BONUS | 1.3 | retrieval.py |
| MAX_RECENCY_PENALTY | 0.7 | retrieval.py |
| FATIGUE_THRESHOLD (默认) | 0.7 | rules.py |
| PERSONALITY_SUMMARY_THRESHOLD | 2 | summarizer.py |
| OVERALL_PERSONALITY_THRESHOLD | 3 | summarizer.py |
| HTTP read timeout | 12h | _http.py |
| Embedding batch size | 32 | embedding.py |
| Embedding retry | 3次 | embedding.py |

## 未解决问题

1. 反馈学习：`update_feedback` 将反馈写入 `feedback.toml`，但数据当前仅存储未消费（无反馈驱动的策略权重更新）
2. 多用户隔离：当前单驾驶员场景，未实现
