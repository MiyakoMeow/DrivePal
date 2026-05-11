# 模型配置

`config/llm.toml`。**model_groups + model_providers** 组合模式。

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4  # provider 级别最大并发数

[embedding]
model = "local/text-embedding-bge-m3"
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `DATA_DIR` | 数据目录路径（默认 data） |
| `WEBUI_DIR` | WebUI静态文件目录路径（默认 webui/） |
| `MINIMAX_API_KEY` | MiniMax API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ZHIPU_API_KEY` | 智谱 API Key |
| `JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY` | Judge 模型配置 |
| `FATIGUE_THRESHOLD` | 疲劳规则阈值（默认0.7） |
| `PROBABILISTIC_INFERENCE_ENABLED` | 概率推断开关（默认1） |
| `MEMORYBANK_SEED` | 遗忘随机种子（benchmark复现用） |
| `MEMORYBANK_FORGET_MODE` | 遗忘模式：deterministic/probabilistic |
| `MEMORYBANK_ENABLE_FORGETTING` | 启用遗忘（默认关闭） |
| `MEMORYBANK_CHUNK_SIZE` | 检索分块大小（默认1500） |
| `MEMORYBANK_LLM_TEMPERATURE` | LLM 温度（None=使用ChatModel默认，摘要默认0.3） |
| `MEMORYBANK_EMBEDDING_BATCH_SIZE` | 嵌入批量大小（默认100） |
| `MEMORYBANK_SAVE_INTERVAL_SECONDS` | 持久化节流间隔（默认30秒） |
| `MEMORYBANK_REFERENCE_DATE_AUTO` | 启用自动推算参考日期（默认false） |
