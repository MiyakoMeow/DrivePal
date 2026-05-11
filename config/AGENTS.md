# config - 配置文件目录

## llm.toml

模型配置。**model_groups + model_providers** 组合模式。`api_key_env` 字段指定环境变量名，`_resolve_api_key()` 运行时读取。

```toml
[model_groups.default]
models = ["deepseek/deepseek-v4-flash?temperature=0.0"]

[model_providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
concurrency = 8

[model_groups.judge]
models = ["zhipu-coding/glm-4.5-air?temperature=0.1"]

[model_providers.zhipu-coding]
base_url = "https://open.bigmodel.cn/api/coding/paas/v4"
api_key_env = "ZHIPU_API_KEY"
concurrency = 3

[model_providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
concurrency = 16

[embedding]
model = "openrouter/baai/bge-m3"
```

`judge_model_group` 顶层键指定 Judge 模型组名（默认 `"judge"`）。

### 环境变量

| 变量 | 说明 |
|------|------|
| `CONFIG_PATH` | 自定义配置文件路径（默认 config/llm.toml） |
| `DATA_DIR` | 数据目录路径（默认 data） |
| `WEBUI_DIR` | WebUI 静态文件目录路径（默认 webui/） |
| `FATIGUE_THRESHOLD` | 疲劳规则阈值（默认0.7） |
| `PROBABILISTIC_INFERENCE_ENABLED` | 概率推断开关（默认1） |
| `MEMORYBANK_SEED` | 遗忘随机种子（benchmark复现用） |
| `MEMORYBANK_FORGET_MODE` | 遗忘模式：deterministic/probabilistic |
| `MEMORYBANK_ENABLE_FORGETTING` | 启用遗忘（默认关闭） |
| `MEMORYBANK_CHUNK_SIZE` | 检索分块大小（默认1500） |
| `MEMORYBANK_EMBEDDING_BATCH_SIZE` | 嵌入批量大小（默认100） |
| `MEMORYBANK_SAVE_INTERVAL_SECONDS` | 持久化节流间隔（默认30秒） |
| `MEMORYBANK_REFERENCE_DATE_AUTO` | 启用自动推算参考日期（默认false） |
| `MEMORYBANK_LLM_TEMPERATURE` | MemoryBank 摘要 LLM 温度覆盖 |
| `MEMORYBANK_LLM_MAX_TOKENS` | MemoryBank 摘要 LLM max_tokens 覆盖 |

## rules.toml

安全规则数据驱动配置，由 `app/agents/rules.py` 的 `load_rules()` 加载。

包含 7 条规则（高速仅音频、疲劳抑制、过载延后、停车全通道、city_driving 限制、traffic_jam 安抚、乘客在场放宽）。条件字段支持 AND 组合：`scenario` / `not_scenario` / `workload` / `fatigue_above` / `has_passengers`。

详见 `app/agents/AGENTS.md`。
