# LLM Provider 并发可配置实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持在 provider 层配置并发上限，废弃全局硬编码的 semaphore

**Architecture:** 
- `LLMProviderConfig` 新增 `concurrency` 字段存储 provider 级别并发上限
- `ChatModel` 使用 provider 名称作为 key 的 semaphore 缓存，按 provider 独立控制并发
- 每个 provider 的请求先获取对应 semaphore slot，再执行

**Tech Stack:** asyncio.Semaphore, dataclass

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `app/models/settings.py` | 新增 `concurrency` 字段，修改配置解析 |
| `app/models/chat.py` | 实现 provider 级别 semaphore 缓存 |
| `config/llm.toml` | 各 provider 添加 `concurrency` 字段 |
| `tests/test_settings.py` | 新增 concurrency 配置解析测试 |
| `tests/test_chat.py` | 新增并发控制行为测试 |

---

## Task 1: 修改 `LLMProviderConfig` 添加 concurrency 字段

**Files:**
- Modify: `app/models/settings.py:36-46`

- [ ] **Step 1: 修改 `LLMProviderConfig` 数据类，添加 `concurrency` 字段**

```python
@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    provider: ProviderConfig
    temperature: float = 0.7
    concurrency: int = 4  # 新增字段，默认值4

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        """从字典创建配置实例."""
        provider, extra = _build_provider_config_from_dict(d, {"temperature": 0.7, "concurrency": 4})
        return cls(provider=provider, **extra)
```

- [ ] **Step 2: 修改 `_build_provider_config_from_ref` 读取 provider concurrency**

修改 `app/models/settings.py:259-266`，在返回 `LLMProviderConfig` 时传入 concurrency：
```python
concurrency = provider_config.get("concurrency", 4)
return LLMProviderConfig(
    provider=ProviderConfig(
        model=resolved.model_name,
        base_url=provider_config.get("base_url"),
        api_key=api_key,
    ),
    temperature=resolved.params.get("temperature", 0.7),
    concurrency=concurrency,
)
```

- [ ] **Step 3: 运行测试验证**

Run: `uv run ty check app/models/settings.py`
Expected: 无类型错误

- [ ] **Step 4: 提交**

```bash
git add app/models/settings.py
git commit -m "feat(settings): 添加 LLMProviderConfig.concurrency 字段"
```

---

## Task 2: 实现 provider 级别 Semaphore 缓存

**Files:**
- Modify: `app/models/chat.py:1-137`

- [ ] **Step 1: 移除全局 semaphore，新增 provider_semaphore_cache**

```python
# 移除: _llm_semaphore = asyncio.Semaphore(4)

_provider_semaphore_cache: dict[str, asyncio.Semaphore] = {}
_provider_semaphore_lock = asyncio.Lock()
```

- [ ] **Step 2: 新增 `_get_provider_semaphore` 函数**

```python
async def _get_provider_semaphore(provider_name: str, concurrency: int) -> asyncio.Semaphore:
    """获取或创建 provider 级别的 semaphore."""
    async with _provider_semaphore_lock:
        if provider_name not in _provider_semaphore_cache:
            _provider_semaphore_cache[provider_name] = asyncio.Semaphore(concurrency)
        return _provider_semaphore_cache[provider_name]
```

- [ ] **Step 3: 修改 `ChatModel.__init__` 存储 providers**

`ChatModel.__init__` 保持不变，但需要确保 provider 名称可用。`ChatModel` 需要能获取每个 provider 的名称和 concurrency。

- [ ] **Step 4: 新增 `_acquire_slot` 和 `_release_slot` 方法**

```python
async def _acquire_slot(self, provider: LLMProviderConfig) -> asyncio.Semaphore:
    """获取 provider 的 semaphore slot."""
    return await _get_provider_semaphore(provider.provider.model, provider.concurrency)

async def _run_with_semaphore(self, provider: LLMProviderConfig, coro):
    """使用 provider semaphore 执行协程."""
    sem = await self._acquire_slot(provider)
    async with sem:
        return await coro
```

- [ ] **Step 5: 修改 `generate` 方法使用 provider semaphore**

```python
async def generate(
    self,
    prompt: str,
    system_prompt: str | None = None,
    **_kwargs: object,
) -> str:
    """异步生成回复."""
    messages = self._build_messages(prompt, system_prompt)
    errors = []
    for provider in self.providers:
        try:
            client = self._create_async_client(provider)
            coro = client.chat.completions.create(
                model=provider.provider.model,
                messages=messages,
                temperature=self._get_temperature(provider),
            )
            response = await self._run_with_semaphore(provider, coro)
            return response.choices[0].message.content or ""
        except Exception as e:
            errors.append(f"{provider.provider.model}: {e}")
            continue
    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
```

- [ ] **Step 6: 同样修改 `generate_stream` 方法**

`generate_stream` 使用 `async with _llm_semaphore` 的地方改为使用 provider semaphore。

- [ ] **Step 7: 运行测试验证**

Run: `uv run ty check app/models/chat.py`
Expected: 无类型错误

- [ ] **Step 8: 提交**

```bash
git add app/models/chat.py
git commit -m "feat(chat): 实现 provider 级别并发控制"
```

---

## Task 3: 更新 `config/llm.toml` 添加 concurrency 字段

**Files:**
- Modify: `config/llm.toml`

- [ ] **Step 1: 为各 provider 添加 concurrency 字段**

```toml
[model_providers.local]
base_url = "http://127.0.0.1:50721/v1"
api_key = "none"
concurrency = 4

[model_providers.minimax-cn]
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"
concurrency = 4

[model_providers.zhipuai-coding-plan]
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key_env = "ZHIPU_API_KEY"
concurrency = 4

[model_providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
concurrency = 8
```

- [ ] **Step 2: 提交**

```bash
git add config/llm.toml
git commit -m "chore(config): 为各 provider 添加 concurrency 字段"
```

---

## Task 4: 新增配置解析测试

**Files:**
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 新增 `concurrency` 字段测试**

```python
def test_llm_provider_config_with_concurrency(self) -> None:
    """验证 concurrency 字段被正确解析."""
    cfg = LLMProviderConfig.from_dict(
        {
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "concurrency": 8,
        }
    )
    assert cfg.concurrency == 8

def test_llm_provider_config_concurrency_defaults(self) -> None:
    """验证 concurrency 默认值为 4."""
    cfg = LLMProviderConfig.from_dict({"model": "test"})
    assert cfg.concurrency == 4
```

- [ ] **Step 2: 新增 `get_model_group_providers` 返回 concurrency 的测试**

```python
def test_get_model_group_providers_includes_concurrency(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 get_model_group_providers 返回的配置包含 concurrency."""
    config = {
        "model_groups": {
            "default": {"models": ["openai/gpt-4"]},
        },
        "model_providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-a",
                "concurrency": 16,
            },
        },
    }
    config_file = tmp_path / "config" / "llm.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(tomli_w.dumps(config))
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from adapters.model_config import _load_config
    _load_config.cache_clear()
    settings = LLMSettings.load()
    providers = settings.get_model_group_providers("default")
    assert providers[0].concurrency == 16
    _load_config.cache_clear()
```

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add tests/test_settings.py
git commit -m "test(settings): 新增 concurrency 配置解析测试"
```

---

## Task 5: 新增并发控制行为测试

**Files:**
- Modify: `tests/test_chat.py`

- [ ] **Step 1: 新增 `TestProviderConcurrency` 测试类**

```python
class TestProviderConcurrency:
    """Provider 级别并发控制测试."""

    async def test_concurrent_requests_respected(self) -> None:
        """验证并发请求受 provider semaphore 限制."""
        from app.models.chat import ChatModel, _provider_semaphore_cache
        from app.models.settings import LLMProviderConfig, ProviderConfig

        _provider_semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="test-model",
                    base_url="http://fake:8000/v1",
                    api_key="sk-test",
                ),
                concurrency=2,
            )
        ]
        chat = ChatModel(providers=providers)
        
        active_count = 0
        max_active = 0
        call_times: list[int] = []

        async def mock_create(*args, **kwargs):
            nonlocal active_count, max_active
            call_times.append(id(asyncio.current_task()))
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            return mock_response

        with patch.object(chat, "_create_async_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create = mock_create
            mock_create_client.return_value = mock_client
            
            tasks = [chat.generate(f"prompt{i}") for i in range(4)]
            results = await asyncio.gather(*tasks)

        assert max_active == 2
        assert len(results) == 4

    async def test_different_providers_have_independent_semaphores(self) -> None:
        """验证不同 provider 的 semaphore 独立."""
        from app.models.chat import ChatModel, _provider_semaphore_cache, _get_provider_semaphore
        from app.models.settings import LLMProviderConfig, ProviderConfig

        _provider_semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(model="model-a", base_url="http://a:8000", api_key="sk-a"),
                concurrency=2,
            ),
            LLMProviderConfig(
                provider=ProviderConfig(model="model-b", base_url="http://b:8000", api_key="sk-b"),
                concurrency=3,
            ),
        ]
        chat = ChatModel(providers=providers)
        
        sem_a = await _get_provider_semaphore("model-a", 2)
        sem_b = await _get_provider_semaphore("model-b", 3)
        
        assert sem_a._value == 2
        assert sem_b._value == 3
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/test_chat.py::TestProviderConcurrency -v`
Expected: 所有测试通过

- [ ] **Step 3: 提交**

```bash
git add tests/test_chat.py
git commit -m "test(chat): 新增 provider 并发控制行为测试"
```

---

## Task 6: 运行完整检查

- [ ] **Step 1: 运行 ruff check**

Run: `uv run ruff check --fix app/models/settings.py app/models/chat.py tests/test_settings.py tests/test_chat.py`
Expected: 无错误

- [ ] **Step 2: 运行 ty check**

Run: `uv run ty check app/models/settings.py app/models/chat.py`
Expected: 无错误

- [ ] **Step 3: 运行 ruff format**

Run: `uv run ruff format app/models/settings.py app/models/chat.py tests/test_settings.py tests/test_chat.py`

- [ ] **Step 4: 运行完整测试**

Run: `uv run pytest tests/test_settings.py tests/test_chat.py -v`
Expected: 所有测试通过

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: 实现 provider 级别并发可配置"
```

---

## 验证清单

- [ ] `LLMProviderConfig` 有 `concurrency` 字段，默认值 4
- [ ] `_build_provider_config_from_ref` 正确读取 provider 的 concurrency
- [ ] `_provider_semaphore_cache` 正确缓存 provider 级别的 semaphore
- [ ] `generate` 和 `generate_stream` 使用 provider 级别的 semaphore
- [ ] `config/llm.toml` 各 provider 配置了合适的 concurrency 值
- [ ] 新增测试覆盖配置解析和并发行为
- [ ] ruff/ty 检查通过，测试通过
