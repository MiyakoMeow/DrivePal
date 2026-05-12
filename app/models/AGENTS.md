# 模型封装

`app/models/` —— AI 模型封装层。

## LLM 调用特性

- 多 provider（服务商）自动 fallback（provider 列表顺序）
- provider 级别 semaphore（信号量）限制并发（共享同一 base_url 的 provider 共享 semaphore）
- 12 小时 read timeout（长时推理不断开）
- JSON mode 支持（`response_format={"type": "json_object"}`）
- MemoryBank 摘要调用默认 temperature=0.3、max_tokens=400（可通过 `MEMORYBANK_LLM_TEMPERATURE` / `MEMORYBANK_LLM_MAX_TOKENS` 环境变量覆盖，见 app/memory/AGENTS.md）

## 模块全景

`app/models/` 包含以下模块：

| 文件 | 职责 |
|------|------|
| `chat.py` | LLM chat completion，多 provider fallback、semaphore 并发控制、JSON mode |
| `embedding.py` | 文本嵌入模型封装，OpenAI 兼容远程接口、batch 处理、自动重试 |
| `settings.py` | LLM/Embedding 配置加载器，从 TOML 文件读取模型配置 |
| `model_string.py` | 模型引用字符串格式解析（如 `"provider_name/model_group"`，格式错误抛出 `InvalidModelStringError`）。存在性校验由 `settings.py` 负责 |
| `types.py` | 基础类型定义（`ResolvedModel`、`ProviderConfig` 等） |
| `exceptions.py` | 模型层异常（`ProviderNotFoundError`、`ModelGroupNotFoundError`） |
| `_http.py` | HTTP 客户端共享超时配置（12h read timeout） |

## 错误处理

| 异常类 | 触发条件 |
|--------|----------|
| `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| `ModelGroupNotFoundError` | 引用字符串中 model_group 未配置 |
| `InvalidModelStringError` | 模型引用字符串格式错误 |
| `ChatError` | LLM chat 调用通用失败 |
| `NoProviderError` | provider 列表为空 |
| `AllProviderFailedError` | 所有 provider 均失败 |
| `NoLLMConfigurationError` | 未找到 LLM 配置 |
| `MissingModelFieldError` | 模型配置缺少必需字段 |
| `NoDefaultModelGroupError` | 未设置默认 model group |
| `NoJudgeModelConfiguredError` | 未配置评测模型 |

## 关键阈值

| 阈值 | 值 | 位置 |
|------|-----|------|
| HTTP read timeout | 12h | `_http.py` |
| Embedding batch size（入口默认） | 100 | `get_cached_embedding_model` |
| Embedding batch size（类默认） | 32 | `EmbeddingModel.__init__` |
| Embedding retry | 3 次（指数退避） | `embedding.py` |
