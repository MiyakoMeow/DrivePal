# LLM 并发上限可配置化设计

## 背景

当前 LLM 请求的并发上限硬编码为 4（`asyncio.Semaphore(4)`），无法灵活配置。

## 需求

1. **并发上限可配置**：在 provider 层或 group 层设置，而不是硬编码
2. **其它 LLM 配置只能指定 group**：如 `temperature` 等参数只能通过 group 指定
3. **优先级规则**：
   - 单 provider 在 group 中：`min(provider_concurrency, group_concurrency)`
   - 多 provider 在同一 group：provider 上限仍有效，超出部分竞争 group 剩余资源

## 配置结构

### TOML 配置文件 (`config/llm.toml`)

| 位置 | 字段 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model_providers.xxx` | `concurrency` | 否 | 4 | 该 provider 的并发上限 |
| `model_groups.xxx` | `concurrency` | 否 | 4 | 该 group 的总并发上限 |
| `model_groups.xxx` | `models` | 是 | - | 模型引用列表，格式 `"provider/model?temperature=0.1"` |

### 配置示例

```toml
[model_groups.default]
concurrency = 8
models = ["local/qwen3.5-2b"]

[model_groups.smart]
concurrency = 16
models = ["deepseek/deepseek-chat"]

[model_providers.minimax-cn]
concurrency = 4
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"

[model_providers.deepseek]
concurrency = 8
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
```

## 核心概念

### 两层并发控制

1. **Provider 级别**：每个 provider 有独立的并发上限，防止对单个 API 服务造成过大压力
2. **Group 级别**：整个 group 有总并发上限，限制资源总占用

### 多 Provider 资源竞争模型

Group 内的多个 provider 共享 group 总资源，遵循以下规则：

1. **所有请求首先受 group `concurrency` 全局限制** — 只有获取到 group slot 的请求才能继续
2. **在 group 限额内，每个 provider 受自身 `concurrency` 限制** — provider 之间平等竞争
3. 当 group 总 slot 满时，新请求在 group 层面等待（先到先得）
4. Provider 之间不保障固定比例，按请求到达顺序竞争

## 实现方案概述

### 1. 数据结构变更

**新增 `ConcurrencyConfig` 数据类**：
- `provider_limit: int` — 该 provider 的并发上限
- `group_limit: int` — 该 group 的总并发上限

**修改 `LLMProviderConfig`**：
- 新增可选字段 `concurrency: ConcurrencyConfig | None`

### 2. 配置解析逻辑

`_build_provider_config_from_ref` 返回带并发约束的配置：
- 从 `model_providers` 读取 provider 级别的 concurrency
- 从 `model_groups` 读取 group 级别的 concurrency
- 两者独立存储，不做 min 运算（运行时根据场景计算）

### 3. Semaphore 管理

废弃全局 `_llm_semaphore`，改为按 group 隔离的 semaphore：

- `_group_semaphore_cache: dict[str, asyncio.Semaphore]` — group 级 semaphore 缓存
- `_provider_semaphore_cache: dict[str, asyncio.Semaphore]` — provider 级 semaphore 缓存
- 异步锁保护缓存访问
- 支持动态创建和按需扩展

### 4. ChatModel 变更

`ChatModel` 新增参数：
- `group_name: str | None` — 模型组名称
- `group_concurrency: int | None` — group 级并发上限

核心逻辑：
- `_acquire_slot()` — 先获取 group 级别 slot，再获取 provider 级别 slot
- `_release_slot()` — 释放对应的 slot
- `generate()` — 两级并发控制下的 provider fallback

### 5. 工厂函数

```python
def get_chat_model(
    group_name: str = "default",
    temperature: float | None = None,
) -> ChatModel:
    """从配置创建 ChatModel 实例."""
```

从配置读取对应 group 的 providers 和 concurrency，创建实例。

## 行为示例

### 单 Provider 场景

| Provider 并发 | Group 并发 | 实际并发 |
|---------------|------------|----------|
| 4 | 4 (default) | 4 |
| 4 | 8 | 4 |
| 4 | 2 | 2 |
| 4 (default) | 8 | 4 |

**规则**：单 provider 时，实际并发 = `min(provider_concurrency, group_concurrency)`

### 多 Provider 场景

假设 `smart` 组配置：
- `group_concurrency = 8`
- `minimax-cn` provider: `concurrency = 4`
- `deepseek` provider: `concurrency = 8`

**行为**：
- `minimax-cn` 最多 4 个并发请求
- `deepseek` 最多 8 个并发请求
- 但两组总计最多 8 个并发（受 group 限制）
- 当 8 个 slot 满时，新请求等待，先到先得

| 实际场景 | minimax-cn | deepseek | 总计 |
|---------|------------|----------|------|
| 正常 | 2 | 3 | 5 |
| deepseek 压力 | 1 | 7 (达到 group 上限) | 8 |
| 全部压力 | 4 | 4 (达到平衡) | 8 |
| provider 耗尽 | 4 (provider 满) | 2 | 6/8 |

## 待解决问题

无。

## 涉及文件

- `config/llm.toml` — 添加 concurrency 字段
- `app/models/settings.py` — 新增 ConcurrencyConfig、修改解析逻辑
- `app/models/chat.py` — 使用动态 semaphore、两级并发控制
