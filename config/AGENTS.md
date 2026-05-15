# 配置

`config/` — 模型、规则、快捷配置。

| 文件 | 说明 |
|------|------|
| llm.toml | model_groups + model_providers |
| rules.toml | 规则引擎规则定义 |
| shortcuts.toml | 快捷命令定义 |
| voice.toml | 语音流水线配置（麦克风/VAD/ASR模型） |
| scheduler.toml | 主动调度器配置（轮询间隔/去抖/周期回顾） |
| tools.toml | 工具开关与约束 |

## llm.toml 示例

```toml
[model_groups.default]
models = ["deepseek/deepseek-v4-flash?temperature=0.0"]

[model_providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
concurrency = 8

[embedding]
model = "openrouter/baai/bge-m3"
```

核心模式：model_groups 定义模型组(default/smart/fast/balanced/judge)，model_providers 定义连接信息。引用格式 `provider/model?params`。

## 环境变量

| 变量 | 说明 |
|------|------|
| CONFIG_PATH | 自定义配置路径（默认 config/llm.toml） |
| DATA_DIR | 数据目录（默认 data） |
| WEBUI_DIR | WebUI目录（默认项目根/webui/） |
| DEEPSEEK_API_KEY | DeepSeek API Key |
| ZHIPU_API_KEY | 智谱 API Key |
| OPENROUTER_API_KEY | OpenRouter API Key |
| JUDGE_MODEL / JUDGE_BASE_URL | 消融实验Judge配置 |
| SECONDARY_JUDGE_MODEL | 安全组二次裁判模型 |
| ABLATION_SEED | 消融实验随机种子 |
| ABLATION_VARIANT_TIMEOUT_SECONDS | 单variant超时（默认300） |
| FATIGUE_THRESHOLD | 疲劳规则阈值（默认0.7） |
| PROBABILISTIC_INFERENCE_ENABLED | 概率推断开关（默认1） |
| MEMORYBANK_ENABLE_FORGETTING | 启用遗忘（默认关闭） |
| MEMORYBANK_FORGET_MODE | deterministic/probabilistic |
| MEMORYBANK_SOFT_FORGET_THRESHOLD | 软遗忘阈值（默认0.3） |
| MEMORYBANK_FORGET_INTERVAL_SECONDS | 遗忘间隔（默认300） |
| MEMORYBANK_FORGETTING_TIME_SCALE | 遗忘时间尺度（默认1.0） |
| MEMORYBANK_CHUNK_SIZE | 分块大小（None=自适应） |
| MEMORYBANK_DEFAULT_CHUNK_SIZE | 自适应回退（默认1500） |
| MEMORYBANK_CHUNK_SIZE_MIN/MAX | 200/8192 |
| MEMORYBANK_LLM_TEMPERATURE | 摘要温度（None→0.3） |
| MEMORYBANK_LLM_MAX_TOKENS | 摘要max_tokens（None→400） |
| MEMORYBANK_EMBEDDING_BATCH_SIZE | 嵌入批量（默认100） |
| MEMORYBANK_SAVE_INTERVAL_SECONDS | 持久化节流（默认30s） |
| MEMORYBANK_COARSE_SEARCH_FACTOR | 粗搜倍数（默认4） |
| MEMORYBANK_EMBEDDING_MIN_SIMILARITY | 最低相似度（默认0.3） |
| MEMORYBANK_MAX_MEMORY_STRENGTH | 记忆强度上限（默认10） |
| MEMORYBANK_RETRIEVAL_ALPHA | 语义vs留存权衡（默认0.7） |
| MEMORYBANK_BM25_FALLBACK_ENABLED | BM25回退（默认true） |
| MEMORYBANK_BM25_FALLBACK_THRESHOLD | BM25回退阈值（默认0.5） |
| MEMORYBANK_REFERENCE_DATE | 固定参考日期 |
| MEMORYBANK_SHUTDOWN_TIMEOUT_SECONDS | 关闭超时（默认30s） |

完整列表见 `app/memory/memory_bank/config.py` 的 `MemoryBankConfig`。
