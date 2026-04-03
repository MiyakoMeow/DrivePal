# LLM 并发上限可配置化设计

## 背景

当前 LLM 请求的并发上限硬编码为 4（`asyncio.Semaphore(4)`），无法灵活配置。

## 需求

1. **并发上限可配置**：在 provider 层设置，而不是硬编码
2. **其它 LLM 配置只能指定 group**：如 `temperature` 等参数只能通过 group 指定
3. **并发控制逻辑**：请求受 provider 级别 semaphore 限制

## 配置结构

### TOML 配置文件 (`config/llm.toml`)

| 位置 | 字段 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model_providers.xxx` | `concurrency` | 否 | 4 | 该 provider 的并发上限 |

### 配置示例

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_groups.smart]
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

### Provider 级别并发控制

每个 provider 有独立的并发上限，防止对单个 API 服务造成过大压力：
- 每个 provider 独立管理自己的 semaphore
- 请求在 provider 级别竞争资源
- 支持动态创建和按需扩展

## 实现方案概述

### 1. 数据结构变更

**新增 `ConcurrencyConfig` 数据类**：
- `provider_limit: int` — 该 provider 的并发上限

**修改 `LLMProviderConfig`**：
- 新增可选字段 `concurrency: int | None`

### 2. 配置解析逻辑

`_build_provider_config_from_ref` 返回带并发约束的配置：
- 从 `model_providers` 读取 provider 级别的 concurrency
- 运行时创建对应 provider 的 semaphore

### 3. Semaphore 管理

废弃全局 `_llm_semaphore`，改为按 provider 隔离的 semaphore：

- `_provider_semaphore_cache: dict[str, asyncio.Semaphore]` — provider 级 semaphore 缓存
- 异步锁保护缓存访问
- 支持动态创建和按需扩展

### 4. ChatModel 变更

`ChatModel` 新增参数：
- `provider_name: str` — provider 名称
- `provider_concurrency: int` — provider 级并发上限

核心逻辑：
- `_acquire_slot()` — 获取 provider 级别 slot
- `_release_slot()` — 释放对应的 slot
- `generate()` — 并发控制下的 provider fallback

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

| Provider 并发 | 实际并发 |
|---------------|----------|
| 4 | 4 |
| 8 | 8 |
| 2 | 2 |

**规则**：实际并发 = `provider_concurrency`

### 多 Provider 场景（同 group）

假设 `smart` 组配置：
- `minimax-cn` provider: `concurrency = 4`
- `deepseek` provider: `concurrency = 8`

**行为**：
- `minimax-cn` 最多 4 个并发请求
- `deepseek` 最多 8 个并发请求
- 两组之间相互独立，各自受自身限制

| 场景 | minimax-cn | deepseek |
|------|------------|----------|
| 正常 | 2 | 3 |
| deepseek 压力 | 1 | 7 |
| 全部压力 | 4 | 8 |

## 待解决问题

无。

## 涉及文件

- `config/llm.toml` — 添加 concurrency 字段
- `app/models/settings.py` — 新增 ConcurrencyConfig、修改解析逻辑
- `app/models/chat.py` — 使用动态 semaphore、并发控制
