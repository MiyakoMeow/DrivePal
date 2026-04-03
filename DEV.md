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
models = ["minimax-cn/MiniMax-M2.7?temperature=0.0"]

[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4  # provider 级别最大并发数

[model_providers.minimax-cn]
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"
concurrency = 4

[embedding]
model = "huggingface/BAAI/bge-small-zh-v1.5"
```

**Provider 并发控制：**
- `concurrency`：每个 provider 的最大并发请求数（默认 1），使用 semaphore 实现
- 当同一 provider 被多个 model_groups 引用时，共享同一个 semaphore

**环境变量覆盖：**

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 `config/llm.toml`） |
| `DATA_DIR` | 数据目录路径（默认 `data`），服务启动时自动初始化 |
| `WEBUI_DIR` | WebUI 静态文件目录路径（默认项目根目录下 `webui/`） |
| `MINIMAX_API_KEY` | MiniMax provider API Key（用于 `benchmark` 模型组） |
| `DEEPSEEK_API_KEY` | DeepSeek provider API Key（用于 `smart` 模型组） |
| `ZHIPU_API_KEY` | 智谱 provider API Key（用于 `fast` 模型组） |

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
├── memorybank_personality.toml # MemoryBank 个性分析
├── memochat_recent_dialogs.toml # MemoChat 短期对话缓冲
├── memochat_memos.toml       # MemoChat 主题Memo（{topic → [entries]}）
├── memochat_interactions.toml # MemoChat 交互记录
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

---

## 测试

### 运行所有测试

```bash
uv run pytest tests/ -v
```

### 运行集成测试（需要 LLM provider）

```bash
uv run pytest tests/ -v --run-integration
# 或
INTEGRATION_TESTS=1 uv run pytest tests/ -v
```

### 测试覆盖模块

| 文件 | 说明 |
|------|------|
| `tests/test_adapters/test_common.py` | 适配器通用工具函数 |
| `tests/test_adapters/test_model_config.py` | 模型字符串解析 |
| `tests/test_adapters/test_runner.py` | VehicleMemBench 运行器 |
| `tests/stores/test_memory_bank_store.py` | MemoryBank 后端 |
| `tests/stores/test_memochat_engine.py` | MemoChat 摘要引擎 |
| `tests/stores/test_memochat_prompts.py` | MemoChat 提示词 |
| `tests/stores/test_memochat_retriever.py` | MemoChat 检索策略 |
| `tests/stores/test_memochat_store.py` | MemoChat 后端 |
| `tests/test_context_schemas.py` | 驾驶上下文数据模型 |
| `tests/test_graphql.py` | GraphQL 端点测试 |
| `tests/test_rules.py` | 规则引擎测试 |
| `tests/test_chat.py` | Chat 驱动 LLM 多provider fallback、Workflow 上下文注入 |
| `tests/test_embedding.py` | Embedding 语义检索与聚合 |
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
| **LLM支持** | Qwen3.5-2B (vLLM, 默认), MiniMax-M2.7, DeepSeek-chat, GLM-4.7-flashx |
| **LLM推理** | vLLM (本地部署), OpenAI兼容接口（多provider自动fallback） |
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线+分层摘要+个性分析), MemoChat (对话缓冲+LLM主题摘要) |
| **数据存储** | TOML文件 (tomllib + tomli-w) |
| **数据集** | HuggingFace Datasets |
| **基准测试** | VehicleMemBench (vendor 子模块) |
| **开发工具** | uv (包管理), pytest (测试, asyncio_mode=auto), ruff (lint, 扩展规则集), ty (类型检查) |
