# app/models - AI 模型封装

LLM/Embedding 调用封装层，多 provider 自动 fallback，纯异步。

## 模块结构

| 文件 | 职责 |
|------|------|
| `chat.py` | LLM 调用（多provider fallback, 纯异步, JSON mode） |
| `embedding.py` | Embedding 模型封装（纯远程, 重试 + 批量） |
| `settings.py` | 模型组/Provider 配置加载 |
| `model_string.py` | 模型引用字符串解析（`provider/model?key=value`） |
| `types.py` | `ResolvedModel`, `ProviderConfig` 纯数据类型 |
| `exceptions.py` | `ProviderNotFoundError`, `ModelGroupNotFoundError` |
| `_http.py` | HTTP 超时配置（12h） |

## LLM 调用（chat.py）

- 多 provider 自动 fallback（provider 列表顺序）
- provider 级别 semaphore 限制并发（共享同一 `base_url` 的 provider 共享 semaphore）
- 12 小时 read timeout（长时推理不断开）
- JSON mode 支持（`response_format={"type": "json_object"}`）

## Embedding 模型（embedding.py）

- 纯远程调用（vLLM OpenAI 兼容接口或 OpenRouter）
- 批量编码（默认 batch_size=32；MemoryBank 层默认 100 通过 `MEMORYBANK_EMBEDDING_BATCH_SIZE` 覆盖）
- 3 次指数退避重试

## 模型配置（settings.py）

加载 `config/llm.toml` 的 `model_groups + model_providers` 组合模式。

```toml
[model_groups.default]
models = ["deepseek/deepseek-v4-flash?temperature=0.0"]

[model_providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
concurrency = 8

[model_groups.judge]
models = ["zhipu-coding/glm-4.5-air?temperature=0.1"]

[model_providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
concurrency = 16

[embedding]
model = "openrouter/baai/bge-m3"
```

`api_key_env` 指定环境变量名，`_resolve_api_key()` 运行时读取。`judge_model_group` 键指定 Judge 模型组名（默认 `"judge"`）。

## 模型引用字符串（model_string.py）

格式：`provider/model?key=value`，解析为 `ResolvedModel` 类型。

## 环境变量（models 模块相关）

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `MINIMAX_API_KEY` | MiniMax API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ZHIPU_API_KEY` | 智谱 API Key |
| `MEMORYBANK_LLM_TEMPERATURE` | MemoryBank 摘要 LLM 温度覆盖（summarizer 使用 ChatModel 时回退 0.3） |
| `MEMORYBANK_LLM_MAX_TOKENS` | MemoryBank 摘要 LLM max_tokens 覆盖（summarizer 使用 ChatModel 时回退 400） |
