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

[model_providers.minimax-cn]
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"

[embedding]
model = "huggingface/BAAI/bge-small-zh-v1.5"
```

**环境变量覆盖：**

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 `config/llm.toml`） |
| `MINIMAX_API_KEY` | MiniMax provider API Key（用于 `benchmark` 模型组） |
| `DEEPSEEK_API_KEY` | DeepSeek provider API Key（用于 `smart` 模型组） |
| `ZHIPU_API_KEY` | 智谱 provider API Key（用于 `fast` 模型组） |

### 驾驶场景配置 (`config/scenarios.toml`)

| 类型 | 说明 | 示例模板 |
|------|------|----------|
| `schedule_check` | 日程查询 | "今天有什么安排？" |
| `event_add` | 添加事件 | "提醒我下午三点开会" |
| `event_delete` | 删除事件 | "取消明天的会议" |
| `general` | 通用对话 | "你好" |

### 驾驶员状态配置 (`config/driver_states.toml`)

| 状态 | 说明 | 容忍度 | 合适方式 |
|------|------|--------|----------|
| `focused` | 专注驾驶 | 低 | visual, audio |
| `traffic_jam` | 交通拥堵 | 中 | visual, audio |
| `parked` | 停车状态 | 高 | visual, audio, detailed |
| `highway` | 高速行驶 | 极低 | audio |
| `city_driving` | 城市驾驶 | 低 | visual, audio |

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
└── experiment_results.toml   # 实验结果
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
| `tests/test_integration/test_model_groups.py` | 模型组集成测试 |
| `tests/test_api.py` | API 端点集成测试 |
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
| **AI工作流** | 自定义四阶段 Agent 流水线 |
| **LLM支持** | Qwen3.5-2B (vLLM, 默认), MiniMax-M2.7, DeepSeek-chat, GLM-4.7-flashx |
| **LLM推理** | vLLM (本地部署), OpenAI兼容接口（多provider自动fallback） |
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线+分层摘要+个性分析), MemoChat (对话缓冲+LLM主题摘要) |
| **数据存储** | TOML文件 (tomllib + tomli-w) |
| **数据集** | HuggingFace Datasets |
| **基准测试** | VehicleMemBench (vendor 子模块) |
| **开发工具** | uv (包管理), pytest (测试, asyncio_mode=auto), ruff (lint, 扩展规则集), ty (类型检查) |
