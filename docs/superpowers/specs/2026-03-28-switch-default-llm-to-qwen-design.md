# 设计：将默认 LLM 从 DeepSeek 切换为 qwen3.5-2b

## 背景

项目当前默认使用 DeepSeek (`deepseek-chat`) 作为 LLM。需要将默认 LLM 改为本地 vLLM 部署的 `Qwen/Qwen3.5-2B`，DeepSeek 保留作为备用选项。

## 方案

方案 A（直接替换默认值）：修改配置默认值，deepseek 降为备用。

## 变更范围

### 1. `app/models/config.py`

- `PROVIDERS` 新增 `qwen` 条目：`base_url="http://localhost:8000/v1"`, `model="Qwen/Qwen3.5-2B"`
- `get_provider()` 默认参数从 `"deepseek"` 改为 `"qwen"`

### 2. `app/models/chat.py`

- 默认 `model` 改为 `"Qwen/Qwen3.5-2B"`
- 默认 `base_url` 改为 `"http://localhost:8000/v1"`
- API key 回退：vLLM 本地部署不需要 key，但 `ChatOpenAI` 要求非空，传占位字符串

### 3. `tests/conftest.py`（新增）

- 提供 `is_vllm_available()` 函数，通过 HTTP 请求 `http://localhost:8000/v1/models` 检测 vLLM 是否运行

### 4. `tests/test_chat.py`

- skip 条件从 `not os.getenv("DEEPSEEK_API_KEY")` 改为 `not is_vllm_available()`
- 测试中的 `ChatModel()` 使用默认值（即 qwen）

### 5. `tests/test_api.py`

- 同上，skip 条件改为 vLLM 可用性检测

## 不改动

- `test_memory_bank.py` — MagicMock，不涉及真实 LLM
- `test_experiment_runner.py` — MagicMock，不涉及真实 LLM
- `test_embedding.py` — 与 chat LLM 无关
- `test_storage.py` — 无 LLM
- `app/agents/workflow.py` — 通过 `ChatModel` 间接使用
- `app/memory/memory.py` / `memory_bank.py` — 同上
- `app/api/main.py` — 默认值变更后自动生效

## 向后兼容

手动切换到 deepseek：调用时传入 `model="deepseek-chat", base_url="https://api.deepseek.com/v1", api_key="your-key"`，或使用 `config.py` 的 `get_provider("deepseek")`。
