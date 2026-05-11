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
| `embedding.py` | 文本嵌入模型封装，BGE-M3 调用、batch 处理、自动重试 |
| `settings.py` | LLM/Embedding 配置加载器，从 TOML 文件读取模型配置 |
| `model_string.py` | 模型引用字符串解析（如 `"provider_name/model_group"` → ProviderNotFoundError / ModelGroupNotFoundError） |
| `types.py` | 基础类型定义（ModelConfig、ProviderConfig 等） |
| `exceptions.py` | 模型层异常（ProviderNotFoundError、ModelGroupNotFoundError） |
| `_http.py` | 底层 HTTP 客户端，12h read timeout、连接池管理 |
