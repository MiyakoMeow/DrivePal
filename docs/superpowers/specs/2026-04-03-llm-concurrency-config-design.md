# LLM 并发上限可配置化设计

## 背景

当前 LLM 请求的并发上限硬编码为 4（`_llm_semaphore = asyncio.Semaphore(4)`），无法灵活配置。

## 需求

1. **并发上限可配置**：在 provider 层或 group 层设置，而不是硬编码
2. **其它 LLM 配置只能指定 group**：如 `temperature` 等参数只能通过 group 指定
3. **优先级规则**：
   - 单 provider 在 group 中：`min(provider_concurrency, group_concurrency)`
   - 多 provider 在同一 group：provider 上限仍有效，超出部分竞争 group 剩余资源

## 配置结构

### TOML 配置文件 (`config/llm.toml`)

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

### 字段说明

| 字段 | 位置 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `concurrency` | `model_providers.xxx` | 否 | 4 | 该 provider 的并发上限 |
| `concurrency` | `model_groups.xxx` | 否 | 4 | 该 group 的总并发上限 |
| `models` | `model_groups.xxx` | 是 | - | 模型引用列表，格式 `"provider/model?temperature=0.1"` |

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

## 实现方案

### 1. 数据结构变更

**新增 `ConcurrencyConfig` 数据类**：

```python
@dataclass
class ConcurrencyConfig:
    """并发配置."""
    provider_limit: int = 4  # 该 provider 的并发上限
    group_limit: int = 4    # 该 group 的总并发上限
```

**修改 `LLMProviderConfig`**：

```python
@dataclass
class LLMProviderConfig:
    provider: ProviderConfig
    temperature: float = 0.7
    concurrency: ConcurrencyConfig | None = None  # 新增
```

### 2. 配置解析逻辑

`_build_provider_config_from_ref` 返回带并发约束的配置：

```python
def _build_provider_config_from_ref(
    ref: str,
    model_providers: dict[str, dict],
    group_concurrency: int | None = None,
) -> LLMProviderConfig:
    # ... 解析 provider/model 引用 ...
    
    provider_limit = provider_config.get("concurrency", 4)
    group_limit = group_concurrency or 4
    
    return LLMProviderConfig(
        provider=ProviderConfig(...),
        temperature=temperature,
        concurrency=ConcurrencyConfig(
            provider_limit=provider_limit,
            group_limit=group_limit,  # 记录 group 上限，不做 min
        ),
    )
```

### 3. Semaphore 管理

**废弃全局 `_llm_semaphore`**，改为按 group 隔离的 semaphore：

```python
_group_semaphore_cache: dict[str, asyncio.Semaphore] = {}
_provider_semaphore_cache: dict[str, asyncio.Semaphore] = {}
_semaphore_lock = asyncio.Lock()

async def _get_group_semaphore(group_name: str, concurrency: int) -> asyncio.Semaphore:
    """获取或创建 group 对应的 semaphore."""
    async with _semaphore_lock:
        if group_name not in _group_semaphore_cache:
            _group_semaphore_cache[group_name] = asyncio.Semaphore(concurrency)
        return _group_semaphore_cache[group_name]

async def _get_provider_semaphore(provider_name: str, concurrency: int) -> asyncio.Semaphore:
    """获取或创建 provider 对应的 semaphore."""
    async with _semaphore_lock:
        if provider_name not in _provider_semaphore_cache:
            _provider_semaphore_cache[provider_name] = asyncio.Semaphore(concurrency)
        return _provider_semaphore_cache[provider_name]

async def _release_group_semaphore(group_name: str) -> None:
    """清理 group 的 semaphore（进程退出时调用）。"""
    async with _semaphore_lock:
        _semaphore_cache.pop(group_name, None)
```

### 4. ChatModel 变更

```python
class ChatModel:
    def __init__(
        self,
        providers: list[LLMProviderConfig] | None = None,
        temperature: float | None = None,
        group_name: str | None = None,
        group_concurrency: int | None = None,
    ) -> None:
        # ... 现有逻辑 ...
        self.group_name = group_name
        self.group_concurrency = group_concurrency

    async def _acquire_slot(self) -> None:
        """获取并发 slot，受 provider 和 group 两级限制."""
        semaphore = await _get_group_semaphore(
            self.group_name or "default",
            self.group_concurrency or 4,
        )
        await semaphore.acquire()

    async def _release_slot(self) -> None:
        """释放并发 slot."""
        semaphore = await _get_group_semaphore(
            self.group_name or "default",
            self.group_concurrency or 4,
        )
        semaphore.release()

    async def generate(self, prompt: str, ...) -> str:
        group_sem = await _get_group_semaphore(
            self.group_name or "default",
            self.group_concurrency or 4,
        )
        # 先获取 group 级别的 slot
        await group_sem.acquire()
        try:
            # 在 group 资源保护下，尝试各 provider
            for provider in self.providers:
                provider_limit = provider.concurrency.provider_limit if provider.concurrency else 4
                provider_sem = await _get_provider_semaphore(
                    provider.provider.model,
                    provider_limit,
                )
                if provider_sem.locked():
                    continue
                await provider_sem.acquire()
                try:
                    # ... 执行 LLM 调用 ...
                    return result
                except Exception as e:
                    provider_sem.release()
                    errors.append(f"{provider.provider.model}: {e}")
                    continue
            raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
        finally:
            group_sem.release()
```

### 5. 获取 ChatModel 的工厂函数

```python
def get_chat_model(
    group_name: str = "default",
    temperature: float | None = None,
) -> ChatModel:
    """从配置创建 ChatModel 实例."""
    settings = LLMSettings.load()
    providers = settings.get_model_group_providers(group_name)
    group_concurrency = settings.get_group_concurrency(group_name)
    return ChatModel(
        providers=providers,
        temperature=temperature,
        group_name=group_name,
        group_concurrency=group_concurrency,
    )
```

### 6. LLMSettings 新增方法

```python
def get_group_concurrency(self, name: str) -> int:
    """获取 group 的并发上限."""
    if name not in self.model_groups:
        raise KeyError(f"Model group '{name}' not found")
    return self.model_groups[name].get("concurrency", 4)
```

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
```toml
[model_groups.smart]
concurrency = 8
models = ["minimax-cn/MiniMax-M2.5", "deepseek/deepseek-chat"]
```

```toml
[model_providers.minimax-cn]
concurrency = 4

[model_providers.deepseek]
concurrency = 8
```

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
| 一个 provider 耗尽 | 4/4 | 2/8 | 6 (请求会尝试其他 provider) |

## 待解决问题

无。

## 涉及文件

- `config/llm.toml` — 添加 concurrency 字段
- `app/models/settings.py` — 新增 ConcurrencyConfig、修改解析逻辑
- `app/models/chat.py` — 使用动态 semaphore、两级并发控制
