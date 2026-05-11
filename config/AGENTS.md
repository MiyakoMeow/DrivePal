# config - 配置文件目录

## llm.toml

模型配置。**model_groups + model_providers** 组合模式。

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

### 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `FATIGUE_THRESHOLD` | 疲劳规则阈值（默认0.7） |
| `PROBABILISTIC_INFERENCE_ENABLED` | 概率推断开关（默认1） |
| `MEMORYBANK_SEED` | 遗忘随机种子（benchmark复现用） |
| `MEMORYBANK_FORGET_MODE` | 遗忘模式：deterministic/probabilistic |
| `MEMORYBANK_ENABLE_FORGETTING` | 启用遗忘（默认关闭） |
| `MEMORYBANK_CHUNK_SIZE` | 检索分块大小（默认1500） |
| `MEMORYBANK_EMBEDDING_BATCH_SIZE` | 嵌入批量大小（默认100） |
| `MEMORYBANK_SAVE_INTERVAL_SECONDS` | 持久化节流间隔（默认30秒） |
| `MEMORYBANK_REFERENCE_DATE_AUTO` | 启用自动推算参考日期（默认false） |

## rules.toml

安全规则数据驱动配置，由 `app/agents/rules.py` 的 `load_rules()` 加载。
