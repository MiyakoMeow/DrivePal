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
- MemoryBank 摘要调用默认 temperature=0.3、max_tokens=400（环境变量覆盖）

## Embedding 模型（embedding.py）

- 纯远程调用（vLLM OpenAI 兼容接口）
- 批量编码（默认 batch_size=100）
- 3 次指数退避重试

## 模型配置（settings.py）

加载 `config/llm.toml` 的 `model_groups + model_providers` 组合模式。

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4

[embedding]
model = "local/text-embedding-bge-m3"
```

## 模型引用字符串（model_string.py）

格式：`provider/model?key=value`，解析为 `ResolvedModel` 类型。

## 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `DATA_DIR` | 数据目录路径（默认 data） |
| `WEBUI_DIR` | WebUI 静态文件目录路径（默认 webui/） |
| `MINIMAX_API_KEY` | MiniMax API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ZHIPU_API_KEY` | 智谱 API Key |
| `JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY` | Judge 模型配置 |
| `MEMORYBANK_LLM_TEMPERATURE` | MemoryBank LLM 温度覆盖 |
| `MEMORYBANK_LLM_MAX_TOKENS` | MemoryBank LLM max_tokens 覆盖 |
