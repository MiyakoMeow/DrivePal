# 模型封装

`app/models/` —— AI模型封装层。

## LLM调用特性

- 多provider自动fallback（provider列表顺序）
- provider级别semaphore限制并发（共享同一base_url的provider共享semaphore）
- 12小时read timeout（长时推理不断开）
- JSON mode支持（`response_format={"type": "json_object"}`）
- MemoryBank 摘要调用默认 temperature=0.3、max_tokens=400（可通过 `MEMORYBANK_LLM_TEMPERATURE` / `MEMORYBANK_LLM_MAX_TOKENS` 环境变量覆盖）

## 模块全景

`app/models/` 包含以下模块：

| 文件 | 职责 |
|------|------|
| `chat.py` | LLM chat completion，多 provider fallback、semaphore 并发控制、JSON mode |
| `embedding.py` | 文本嵌入模型封装，OpenAI 兼容远程接口、batch 处理、自动重试 |
| `settings.py` | LLM/Embedding 配置加载器，从 TOML 文件读取模型配置 |
| `model_string.py` | 模型引用字符串格式解析（如 `"provider_name/model_group"`，格式错误抛 InvalidModelStringError）。存在性校验由 settings.py 负责 |
| `types.py` | 基础类型定义（ResolvedModel、ProviderConfig 等） |
| `exceptions.py` | 模型层异常（ProviderNotFoundError、ModelGroupNotFoundError） |
| `_http.py` | HTTP 客户端共享超时配置（12h read timeout） |

## 错误处理

| 异常类 | 触发条件 |
|--------|----------|
| `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| `ModelGroupNotFoundError` | 引用字符串中 model_group 未配置 |

## 关键阈值

| 阈值 | 值 | 位置 |
|------|-----|------|
| HTTP read timeout | 12h | `_http.py` |
| Embedding batch size | 100 | `embedding.py` |
| Embedding retry | 3 次（指数退避） | `embedding.py` |
