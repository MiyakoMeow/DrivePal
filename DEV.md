# 开发指南

## 配置说明

### 模型配置 (`config/llm.json`)

所有 LLM、Embedding 模型配置统一在 `config/llm.json` 管理，Python 侧由 `app/models/settings.py` 加载（`LLMSettings.load()`）。配置采用组合模式：`ProviderConfig`（model/base_url/api_key）被各专用配置（`LLMProviderConfig`/`EmbeddingProviderConfig`）组合引用。

基准测试使用独立的 `benchmark` 配置：

```json
{
  "llm": [
    {
      "model": "qwen3.5-2b",
      "base_url": "http://127.0.0.1:50721/v1",
      "api_key": "none",
      "temperature": 0.7
    }
  ],
  "benchmark": {
    "model": "MiniMax-M2.7",
    "base_url": "https://api.minimaxi.com/v1",
    "api_key_env": "MINIMAX_API_KEY",
    "temperature": 0.0,
    "max_tokens": 8192
  },
  "embedding": [
    {
      "model": "BAAI/bge-small-zh-v1.5",
      "device": "cpu"
    }
  ]
}
```

**环境变量覆盖：**

| 变量 | 说明 |
|------|------|
| `VLLM_BASE_URL` | 默认 LLM provider 的 base_url |
| `OPENAI_MODEL` / `DEEPSEEK_MODEL` | 自动注册为额外 LLM provider |
| `MINIMAX_API_KEY` | 基准测试 API Key（用于 `benchmark.api_key_env`） |

### 驾驶场景配置 (`config/scenarios.json`)

| 类型 | 说明 | 示例模板 |
|------|------|----------|
| `schedule_check` | 日程查询 | "今天有什么安排？" |
| `event_add` | 添加事件 | "提醒我下午三点开会" |
| `event_delete` | 删除事件 | "取消明天的会议" |
| `general` | 通用对话 | "你好" |

### 驾驶员状态配置 (`config/driver_states.json`)

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
├── events.json               # 事件历史（含 interaction_ids）
├── interactions.json          # 原始交互记录（MemoryBank）
├── memorybank_summaries.json  # MemoryBank 层级摘要
│   ├── daily_summaries: {}    # {date → {content, memory_strength, event_count}}
│   └── overall_summary: ""    # 总摘要
├── contexts.json            # 上下文缓存
├── preferences.json         # 用户偏好
├── feedback.json            # 用户反馈记录
├── strategies.json          # 个性化策略
└── experiment_results.json   # 实验结果
```

### 存储接口 (`app/storage/json_store.py`)

```python
store = JSONStore(data_dir, "filename.json", default_factory=list)

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
| `tests/test_adapters/test_model_config.py` | 模型配置加载 |
| `tests/test_adapters/test_runner.py` | VehicleMemBench 运行器 |
| `tests/stores/test_memory_bank_store.py` | MemoryBank 后端 |
| `test_api.py` | API 端点集成测试 |
| `test_chat.py` | Chat 驱动 LLM 记忆搜索、Workflow 上下文注入 |
| `test_embedding.py` | Embedding 语义检索与聚合 |
| `test_memory_bank.py` | 遗忘曲线、层级摘要、交互聚合 |
| `test_storage.py` | 跨实例持久化、反馈策略更新 |
| `test_settings.py` | 模型配置加载与环境变量覆盖 |
| `test_components.py` | 可组合组件 |
| `test_memory_module_facade.py` | MemoryModule 调度层 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web框架** | FastAPI + Uvicorn |
| **AI工作流** | LangChain + LangGraph |
| **LLM支持** | Qwen3.5-2B (vLLM, 默认), DeepSeek-chat, GPT-4, Claude-3 (OpenAI兼容接口) |
| **LLM推理** | vLLM (本地部署), OpenAI兼容接口 |
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线 + 分层摘要) |
| **数据存储** | JSON文件 (标准库json) |
| **数据集** | HuggingFace Datasets |
| **基准测试** | VehicleMemBench (vendor 子模块) |
| **开发工具** | uv (包管理), pytest (测试), ruff (lint), ty (类型检查) |
