# 模型封装

`app/models/` —— AI 模型封装层。

## LLM 调用特性

- 多 provider（服务商）自动 fallback（provider 列表顺序）
- provider 级别 semaphore（信号量）限制并发（共享同一 base_url 的 provider 共享 semaphore）
- 12 小时 read timeout（长时推理不断开；connect=10s、write=60s、pool=60s 由 _http.py 显式配置）
- JSON mode 支持（`response_format={"type": "json_object"}`）
- MemoryBank 摘要调用不使用 provider 级配置，而由 Summarizer 使用 `MemoryBankConfig.llm_temperature`（默认 `None`，回退 `summarizer.py` 的 `_SUMMARY_DEFAULT_TEMPERATURE=0.3`）和 `MemoryBankConfig.llm_max_tokens`（默认 `None`，回退 `_SUMMARY_DEFAULT_MAX_TOKENS=400`）。这些配置可通过 `MEMORYBANK_LLM_TEMPERATURE` / `MEMORYBANK_LLM_MAX_TOKENS` 环境变量覆盖

## 模块全景

`app/models/` 包含以下模块：

| 文件 | 职责 |
|------|------|
| `chat.py` | LLM chat completion，多 provider fallback、semaphore 并发控制、JSON mode |
| `embedding.py` | 文本嵌入模型封装，OpenAI 兼容远程接口、batch 处理、自动重试 |
| `settings.py` | LLM/Embedding 配置加载器，从 TOML 文件读取模型配置（`load()` 使用 `@cache` 装饰器，运行时修改 TOML 不生效，需重启） |
| `model_string.py` | 模型引用字符串格式解析（如 `"provider_name/model"`，格式错误抛出 `InvalidModelStringError`）。存在性校验由 `settings.py` 负责 |
| `types.py` | 基础类型定义（`ResolvedModel`、`ProviderConfig` 等） |
| `exceptions.py` | 基础异常定义（`ProviderNotFoundError`、`ModelGroupNotFoundError`）；其余 8 个异常分散在 `chat.py`、`settings.py`、`model_string.py` 中 |
| `_http.py` | HTTP 客户端共享超时配置（12h read timeout；connect=10s、write=60s、pool=60s） |

## 错误处理

| 异常类 | 触发条件 |
|--------|----------|
| `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| `ModelGroupNotFoundError` | 请求的 model_group 名称未在配置中找到 |
| `InvalidModelStringError` | 模型引用字符串格式错误 |
| `ChatError` | LLM chat 调用通用失败 |
| `NoProviderError` | provider 列表为空 |
| `AllProviderFailedError` | 所有 provider 均失败（可选 `details` 参数拼接各 provider 错误信息） |
| `NoLLMConfigurationError` | 未找到 LLM 配置 |
| `MissingModelFieldError` | 模型配置缺少 model 字段（仅校验 `model` 字段） |
| `NoDefaultModelGroupError` | 未设置默认 model group |
| `NoJudgeModelConfiguredError` | 未配置评测模型 |

## 关键阈值

| 阈值 | 值 | 位置 |
|------|-----|------|
| HTTP read timeout | 12h | `_http.py` |
| Embedding batch size（入口默认） | 100 | `get_cached_embedding_model`（全局缓存入口，函数参数默认值） |
| Embedding batch size（类默认） | 32 | `EmbeddingModel.__init__` |
| Embedding retry | 3 次（指数退避） | `embedding.py` |
