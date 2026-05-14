# 模型封装

`app/models/` — AI模型封装层。

## LLM 特性

- 多provider自动fallback（列表顺序）
- provider级semaphore限并发（同base_url共享）
- 12h read timeout（connect=10s, write=60s, pool=60s → `_http.py`）
- JSON mode支持
- MemoryBank摘要调用由 `MemoryBankConfig.llm_temperature`/`llm_max_tokens` 控制，可被 `MEMORYBANK_LLM_TEMPERATURE`/`MEMORYBANK_LLM_MAX_TOKENS` 覆盖

## 模块

| 文件 | 职责 |
|------|------|
| chat.py | LLM chat completion, fallback, semaphore, JSON mode |
| embedding.py | 文本嵌入, OpenAI兼容远程, batch, 自动重试 |
| settings.py | TOML配置加载（`@cache`，运行时改TOML不生效） |
| model_string.py | 模型引用字符串解析（`provider/model`） |
| types.py | `ResolvedModel`/`ProviderConfig` 等基础类型 |
| exceptions.py | 基础异常；其余8个异常分散在各模块 |
| _http.py | HTTP客户端共享超时配置 |

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
