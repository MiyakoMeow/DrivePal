# 模型配置

`config/` 目录包含模型、规则和快捷配置：

| 文件 | 说明 |
|------|------|
| `llm.toml` | 模型组 + provider 配置（见下文） |
| `rules.toml` | 规则引擎规则定义 |
| `shortcuts.toml` | 快捷命令定义 |

`config/llm.toml`。**model_groups + model_providers** 组合模式。

```toml
[model_groups.default]
models = ["deepseek/deepseek-v4-flash?temperature=0.0"]

[model_providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
concurrency = 8

[model_providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
concurrency = 16

[embedding]
model = "openrouter/baai/bge-m3"
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml；相对路径从项目根解析，绝对路径直接使用） |
| `DATA_DIR` | 数据目录路径（默认 data） |
| `WEBUI_DIR` | WebUI静态文件目录路径（默认 webui/） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ZHIPU_API_KEY` | 智谱 API Key |
| `OPENROUTER_API_KEY` | OpenRouter API Key |
| `JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY` | 消融实验 Judge 配置。应用内 Judge 通过 TOML 配置，非此环境变量（预留） |
| `FATIGUE_THRESHOLD` | 疲劳规则阈值（默认0.7） |
| `PROBABILISTIC_INFERENCE_ENABLED` | 概率推断开关（默认1） |
| `MEMORYBANK_SEED` | 遗忘随机种子（benchmark复现用） |
| `MEMORYBANK_FORGET_MODE` | 遗忘模式：deterministic/probabilistic |
| `MEMORYBANK_ENABLE_FORGETTING` | 启用遗忘（默认关闭） |
| `MEMORYBANK_CHUNK_SIZE` | 检索分块大小（默认 None，自适应；回退默认值 1500） |
| `MEMORYBANK_LLM_TEMPERATURE` | LLM 温度（None=使用ChatModel默认，摘要默认0.3） |
| `MEMORYBANK_LLM_MAX_TOKENS` | LLM 最大 token 数（摘要默认400） |
| `MEMORYBANK_EMBEDDING_BATCH_SIZE` | 嵌入批量大小（默认100） |
| `MEMORYBANK_SAVE_INTERVAL_SECONDS` | 持久化节流间隔（默认30秒） |
| `MEMORYBANK_REFERENCE_DATE_AUTO` | 启用自动推算参考日期（默认false） |
| `MEMORYBANK_SOFT_FORGET_THRESHOLD` | 软遗忘阈值（默认0.3） |
| `MEMORYBANK_FORGET_INTERVAL_SECONDS` | 遗忘判断最小间隔秒数（默认300） |
| `MEMORYBANK_FORGETTING_TIME_SCALE` | 遗忘时间尺度（默认1.0） |
| `MEMORYBANK_DEFAULT_CHUNK_SIZE` | 自适应回退分块大小（默认1500） |
| `MEMORYBANK_CHUNK_SIZE_MIN` | 最小分块（默认200） |
| `MEMORYBANK_CHUNK_SIZE_MAX` | 最大分块（默认8192） |
| `MEMORYBANK_COARSE_SEARCH_FACTOR` | 粗搜倍数（默认4） |
| `MEMORYBANK_EMBEDDING_MIN_SIMILARITY` | 嵌入最低相似度（默认0.3） |
| `MEMORYBANK_MAX_MEMORY_STRENGTH` | 记忆强度上限（默认10） |
| `MEMORYBANK_RETRIEVAL_ALPHA` | 语义相似度 vs 记忆留存率权衡系数（默认0.7） |
| `MEMORYBANK_BM25_FALLBACK_ENABLED` | BM25 稀疏回退开关（默认true） |
| `MEMORYBANK_BM25_FALLBACK_THRESHOLD` | BM25 回退触发阈值（默认0.5） |
| `MEMORYBANK_REFERENCE_DATE` | 固定参考日期（ISO格式，默认None） |
| `MEMORYBANK_SHUTDOWN_TIMEOUT_SECONDS` | 关闭超时秒数（默认30.0） |

> 此为常用子集，完整列表见 `app/memory/memory_bank/config.py` 的 `MemoryBankConfig` 类。
