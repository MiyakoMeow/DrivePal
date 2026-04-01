# Model Groups 配置架构设计

## 背景

现有 `config/llm.toml` 使用扁平结构，仅支持单模型配置。本设计引入 `model_groups` + `model_providers` 分层架构，支持按名称动态选择模型组。

## 目标

支持多模型组动态选择，便于：
- 基准测试对比不同模型
- 运行时按需切换模型
- provider 复用

## 配置格式

```toml
[model_groups.smart]
models = ["deepseek/deepseek-chat"]

[model_groups.fast]
models = ["zhipuai-coding-plan/glm-4.7-flashx?temperature=0.1"]

[model_groups.balanced]
models = ["minimax-cn/MiniMax-M2.5"]

[model_providers.zhipuai-coding-plan]
type = "openai"
name = "ZhipuAI Coding Plan"
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key_env = "ZHIPU_API_KEY"

[model_providers.minimax-cn]
type = "openai"
name = "MiniMax"
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"

[model_providers.deepseek]
type = "openai"
name = "DeepSeek"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
```

## 架构设计

### 模型引用格式

模型引用格式：`{provider_name}/{model_name}`，provider 名即 `model_providers` 中的表名。

Query string 仅支持请求级参数（`temperature`、`max_tokens` 等），在解析时合并到 provider 配置中。

### 核心组件

1. **`adapters/model_config.py`**
   - 新增 `_resolve_provider(provider_name: str) -> dict`：解析 provider 配置
   - 新增 `resolve_model_string(model_str: str) -> tuple[str, str, dict]`：解析 `provider/model?k=v` 格式
   - 新增 `get_model_group_providers(name: str) -> list[LLMProviderConfig]`：按组名获取配置列表

2. **`app/models/settings.py`**
   - 新增 `LLMSettings.model_groups` 字段（`dict[str, list[str]]`）
   - 新增 `get_model_group_providers(name: str) -> list[LLMProviderConfig]`

### 向后兼容

| 旧格式 | 迁移方式 |
|--------|----------|
| `[llm]` | 等价于 `[model_groups.default]`，首次加载时自动映射 |
| `[benchmark]` | 保留，迁移到 `[model_groups.benchmark]` |
| `[benchmark].max_tokens` | 迁移到 `[model_groups.benchmark]` 每个模型的 query string |

### 多模型选择策略

当 group 包含多个模型时：
- **优先级**：按列表顺序作为 fallback 优先级
- **机制**：全部加载到 `ChatModel.llm_providers`，当前一个 provider 调用失败时，自动切换到下一个
- **语义**：这是 **failover 策略**，不是负载均衡或轮询

### 错误处理

| 场景 | 行为 |
|------|------|
| 空 group | 返回空列表 |
| 不存在的 group | 抛 `KeyError` |
| 不存在的 provider | 抛 `ValueError`，提示 provider 未配置 |
| 环境变量缺失 | `api_key` 为空字符串，运行时按需报错 |

## API 设计

```python
@dataclass
class ResolvedModel:
    """解析后的模型引用."""
    provider_name: str
    model_name: str
    params: dict[str, Any]

def resolve_model_string(model_str: str) -> ResolvedModel:
    """解析模型引用，返回解析后的模型信息."""

def get_model_group_providers(name: str) -> list[LLMProviderConfig]:
    """按组名获取 LLMProviderConfig 列表，供 ChatModel 使用."""
    raise KeyError(f"Model group '{name}' not found")
```

## 待实现功能

以下为实现时需完成的功能点：
1. `adapters/model_config.py` 中新增 `_resolve_provider`、`resolve_model_string`、`get_model_group_providers`
2. `app/models/settings.py` 中新增 `LLMSettings.model_groups` 字段和 `get_model_group_providers` 方法
3. 向后兼容逻辑：自动将 `[llm]` 映射为 `[model_groups.default]`
4. 错误处理：空 group 返回 `[]`，不存在 group 抛 `KeyError`，不存在 provider 抛 `ValueError`

## 尚未解决的问题

- [ ] provider type 是否需要支持非 OpenAI 类型（如 azure、anthropic）
