# 模型封装

`app/models/` — AI模型封装层。

## LLM 特性

- 多provider自动fallback（列表顺序）
- provider级semaphore限并发（同base_url共享）
- 12h read timeout（connect=10s, write=60s, pool=60s → `_http.py`）
- JSON mode支持（`response_format={"type": "json_object"}`）
- DeepSeek reasoning_content 流式累积
- `generate_stream()` 支持 tool_calls 分块累积
- API key解析：`_resolve_api_key()` 先读 `api_key_env` 环境变量，无则回退 `api_key` 字段（`settings.py:170`）

## 模块

| 文件 | 职责 |
|------|------|
| chat.py | `ChatModel` — LLM对话模型，多provider fallback、semaphore并发控制、`generate()`/`generate_stream()`（DeepSeek reasoning_content累积、tool_calls分块）、`batch_generate()`（并行批量，semaphore限流）。工厂函数 `get_chat_model()`/`get_judge_model()` |
| embedding.py | `EmbeddingModel` — 文本嵌入，OpenAI兼容远程，`encode()`/`batch_encode()`，3次指数退避重试。缓存管理：`get_cached_embedding_model()`/`clear_embedding_model_cache()`/`reset_embedding_singleton()` |
| settings.py | TOML配置加载（`@cache`，运行时改TOML不生效）。`_resolve_api_key()` 优先读 `api_key_env` 环境变量，无则回退 `api_key` 字段 |
| model_string.py | 模型引用字符串解析（`provider/model`） |
| types.py | `ResolvedModel`/`ProviderConfig` 等基础类型 |
| exceptions.py | 基础异常；其余8个异常分散在各模块 |
| _http.py | HTTP客户端共享超时配置 |

## 缓存生命周期

| 函数 | 作用 | 位置 |
|------|------|------|
| `close_client_cache()` | 关闭所有缓存的 AsyncOpenAI 客户端（lifespan shutdown） | chat.py:55 |
| `clear_semaphore_cache()` | 清理 semaphore + 客户端缓存（测试 teardown） | chat.py:65 |
| `clear_embedding_model_cache()` | 关闭所有 EmbeddingModel 客户端并清除缓存 | embedding.py:63 |
| `reset_embedding_singleton()` | `clear_embedding_model_cache()` 别称（测试用） | embedding.py:216 |

## 异常

| 异常 | 触发 |
|------|------|
| ProviderNotFoundError | provider未配置 |
| ModelGroupNotFoundError | model_group未找到 |
| InvalidModelStringError | 引用字符串格式错 |
| ChatError | LLM调用通用失败 |
| NoProviderError | provider列表空 |
| AllProviderFailedError | 全部provider失败 |
| NoLLMConfigurationError | 无LLM配置 |
| MissingModelFieldError | 缺model字段 |
| NoDefaultModelGroupError | 无默认model group |
| NoJudgeModelConfiguredError | 未配置评测模型 |

## 阈值

| 阈值 | 值 | 位置 |
|------|----|------|
| HTTP read timeout | 12h | _http.py |
| Embedding batch(入口) | 100 | get_cached_embedding_model |
| Embedding batch(类) | 32 | EmbeddingModel.__init__ |
| Embedding retry | 3次指数退避 | embedding.py |
