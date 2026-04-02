# 本地 vLLM 引擎集成 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Qwen3.5-2B 通过内嵌 vLLM AsyncEngine 集成为默认 LLM，支持流式输出和可用性检查。

**Architecture:** 新建 `ChatModelProtocol`（独立文件）统一接口，新建 `VLLMChatModel` 使用 vLLM AsyncEngine，与现有 `ChatModel`（OpenAI SDK）并存。工厂函数根据配置 `type` 字段分发，单例缓存。

**Tech Stack:** vllm, transformers, asyncio

**Spec:** `docs/superpowers/specs/2026-04-02-local-vllm-design.md`

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `app/models/protocol.py` | ChatModelProtocol 定义 |
| 新建 | `app/models/vllm_chat.py` | VLLMChatModel 实现 |
| 修改 | `app/models/chat.py` | 添加 is_available()，导入 Protocol |
| 修改 | `app/models/settings.py` | 工厂路由 + 单例缓存 |
| 修改 | `app/models/memory.py` | 类型注解改用 Protocol |
| 修改 | `app/memory/stores/memory_bank/store.py` | 类型注解改用 Protocol |
| 修改 | `config/llm.toml` | local provider 改为 vllm 类型 |
| 修改 | `pyproject.toml` | 添加 vllm、transformers 依赖 |
| 修改 | `tests/conftest.py` | is_llm_available 改用 model.is_available() |
| 修改 | `tests/test_chat.py` | 适配新接口 |
| 修改 | `tests/test_settings.py` | 适配新 type 字段 |

---

### Task 1: 创建 ChatModelProtocol

**Files:**
- Create: `app/models/protocol.py`
- Modify: `app/models/chat.py`

- [ ] **Step 1: 创建 protocol.py**

```python
"""统一聊天模型协议."""

from __future__ import annotations

from typing import Protocol
from collections.abc import AsyncIterator


class ChatModelProtocol(Protocol):
    """聊天模型统一接口."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str: ...

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]: ...

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
    ) -> list[str]: ...

    def is_available(self) -> bool: ...
```

- [ ] **Step 2: 给 ChatModel 添加 is_available()**

在 `app/models/chat.py` 的 `ChatModel` 类中添加方法：

```python
def is_available(self) -> bool:
    """检查远程 LLM 是否可响应."""
    import requests

    for provider in self.providers:
        if not provider.provider.base_url:
            continue
        try:
            base = provider.provider.base_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            resp = requests.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {provider.provider.api_key}"}
                if provider.provider.api_key
                else {},
                timeout=5,
            )
            if resp.status_code == 200:
                return True
        except Exception:
            continue
    return False
```

- [ ] **Step 3: 更新 memory.py 类型注解**

`app/memory/memory.py`:
- `TYPE_CHECKING` 导入改为 `from app.models.protocol import ChatModelProtocol`
- `chat_model` 属性返回类型改为 `ChatModelProtocol`
- `__init__` 参数类型改为 `Optional["ChatModelProtocol"]`
- `_chat_model` 字段类型改为 `Optional["ChatModelProtocol"]`

- [ ] **Step 4: 更新 store.py 类型注解**

`app/memory/stores/memory_bank/store.py`:
- `TYPE_CHECKING` 导入改为 `from app.models.protocol import ChatModelProtocol`
- `__init__` 参数 `chat_model` 类型改为 `Optional["ChatModelProtocol"]`

- [ ] **Step 5: 更新 workflow.py 类型引用**

`app/agents/workflow.py` 中如引用了 `ChatModel`，无需改动（workflow 不直接 import ChatModel 类型）。

- [ ] **Step 6: 运行 lint 和类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`
Expected: 无错误

- [ ] **Step 7: 运行现有测试确认无破坏**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: 所有测试通过（或因远程 API 不可用被跳过）

- [ ] **Step 8: Commit**

```bash
git add app/models/protocol.py app/models/chat.py app/memory/memory.py app/memory/stores/memory_bank/store.py
git commit -m "refactor: extract ChatModelProtocol, add is_available()"
```

---

### Task 2: 创建 VLLMChatModel

**Files:**
- Create: `app/models/vllm_chat.py`

- [ ] **Step 1: 实现 VLLMChatModel**

```python
"""本地 vLLM 引擎聊天模型."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from vllm import AsyncEngineArgs, AsyncLLMEngine, SamplingParams
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)


class VLLMChatModel:
    """基于 vLLM AsyncEngine 的本地聊天模型."""

    def __init__(
        self,
        model_id: str,
        temperature: float = 0.7,
        tensor_parallel_size: int = 1,
        max_model_len: int = 4096,
        availability_timeout: float = 120.0,
    ) -> None:
        self._model_id = model_id
        self._temperature = temperature
        self._tensor_parallel_size = tensor_parallel_size
        self._max_model_len = max_model_len
        self._availability_timeout = availability_timeout
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_id, trust_remote_code=True
        )
        engine_args = AsyncEngineArgs(
            model=model_id,
            tensor_parallel_size=tensor_parallel_size,
            trust_remote_code=True,
            max_model_len=max_model_len,
        )
        self._engine = AsyncLLMEngine.from_engine_args(engine_args)
        self._request_counter = 0
        logger.info("VLLMChatModel initialized with model=%s", model_id)

    def _next_request_id(self) -> str:
        self._request_counter += 1
        return f"vllm-{self._request_counter}"

    def _build_prompt(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        formatted = self._build_prompt(prompt, system_prompt)
        temperature = kwargs.get("temperature", self._temperature)
        sampling_params = SamplingParams(
            temperature=float(temperature),
            max_tokens=512,
        )
        final_output = None
        async for output in self._engine.generate(
            formatted, sampling_params, request_id=self._next_request_id()
        ):
            final_output = output
        if final_output is None:
            return ""
        return final_output.outputs[0].text

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        formatted = self._build_prompt(prompt, system_prompt)
        temperature = kwargs.get("temperature", self._temperature)
        sampling_params = SamplingParams(
            temperature=float(temperature),
            max_tokens=512,
        )
        prev_text = ""
        async for output in self._engine.generate(
            formatted, sampling_params, request_id=self._next_request_id()
        ):
            current_text = output.outputs[0].text
            delta = current_text[len(prev_text):]
            prev_text = current_text
            if delta:
                yield delta

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
    ) -> list[str]:
        return [await self.generate(p, system_prompt) for p in prompts]

    def is_available(self) -> bool:
        """同步等待引擎就绪，返回是否可用."""
        try:
            return _wait_for_engine(
                self._engine, self._availability_timeout
            )
        except Exception:
            return False


def _wait_for_engine(engine: AsyncLLMEngine, timeout: float) -> bool:
    """同步等待 vLLM 引擎模型加载完成（在新线程中运行 async probe）."""
    import concurrent.futures

    async def _probe() -> bool:
        async for _ in engine.generate(
            "hi",
            SamplingParams(max_tokens=1),
            request_id="health-check",
        ):
            return True
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _probe())
        return future.result(timeout=timeout)
```

- [ ] **Step 2: Commit**

```bash
git add app/models/vllm_chat.py
git commit -m "feat: add VLLMChatModel with streaming and availability check"
```

---

### Task 3: 配置与工厂路由

**Files:**
- Modify: `app/models/settings.py`
- Modify: `config/llm.toml`

- [ ] **Step 1: 修改 settings.py — LLMProviderConfig 增加 type 和 extra 字段**

替换 `settings.py:36-52` 的 `LLMProviderConfig` dataclass 为：

```python
@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    provider: ProviderConfig
    temperature: float = 0.7
    type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            temperature=d.get("temperature", 0.7),
            type=d.get("type"),
        )
```

- [ ] **Step 2: 修改 settings.py — get_model_group_providers 读取 type**

替换 `settings.py:161-188` 中 `get_model_group_providers()` 方法内的 `for ref in model_refs:` 循环体（从 `resolved = resolve_model_string(ref)` 到 `result.append(...)` 结束）为：

```python
    for ref in model_refs:
        resolved = resolve_model_string(ref)
        if resolved.provider_name not in self.model_providers:
            raise ValueError(
                f"Provider '{resolved.provider_name}' not found in model_providers"
            )
        provider_config = self.model_providers[resolved.provider_name]
        api_key_env = provider_config.get("api_key_env")
        if api_key_env:
            api_key: str | None = os.environ.get(api_key_env, "")
        else:
            api_key = provider_config.get("api_key")

        provider_type = provider_config.get("type")
        model_name = (
            provider_config.get("model", resolved.model_name)
            if provider_type == "vllm"
            else resolved.model_name
        )
        extra_keys = {"type", "model", "base_url", "api_key", "api_key_env"}
        extra = {k: v for k, v in provider_config.items() if k not in extra_keys}

        result.append(
            LLMProviderConfig(
                provider=ProviderConfig(
                    model=model_name,
                    base_url=provider_config.get("base_url"),
                    api_key=api_key,
                ),
                temperature=resolved.params.get("temperature", 0.7),
                type=provider_type,
                extra=extra,
            )
        )
```

- [ ] **Step 3: 修改 settings.py — get_chat_model 工厂路由 + 单例**

添加模块级缓存变量，修改 `get_chat_model()`：

```python
_cached_chat_model: ChatModelProtocol | None = None

def get_chat_model(temperature: float | None = None) -> "ChatModelProtocol":
    """从配置创建 ChatModel 实例（单例缓存）."""
    global _cached_chat_model

    from app.models.protocol import ChatModelProtocol

    if _cached_chat_model is not None:
        return _cached_chat_model

    settings = LLMSettings.load()
    if "default" not in settings.model_groups:
        raise RuntimeError("No default model group configured")
    providers = settings.get_model_group_providers("default")
    if not providers:
        raise RuntimeError("No providers in default model group")

    provider = providers[0]
    if provider.type == "vllm":
        from app.models.vllm_chat import VLLMChatModel

        _cached_chat_model = VLLMChatModel(
            model_id=provider.provider.model,
            temperature=provider.temperature,
            **provider.extra,
        )
    else:
        from app.models.chat import ChatModel

        _cached_chat_model = ChatModel(providers=providers, temperature=temperature)

    return _cached_chat_model
```

注意：`_cached_chat_model` 类型注解需要 `TYPE_CHECKING` 保护：
```python
if TYPE_CHECKING:
    from app.models.protocol import ChatModelProtocol
```

- [ ] **Step 4: 修改 config/llm.toml**

```toml
[model_providers.local]
type = "vllm"
model = "Qwen/Qwen3.5-2B"
tensor_parallel_size = 1
```

删除 `base_url` 和 `api_key`。其他 provider 配置不变。

- [ ] **Step 5: 运行 lint 和类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 6: Commit**

```bash
git add app/models/settings.py config/llm.toml
git commit -m "feat: add vLLM provider type routing and singleton cache"
```

---

### Task 4: 添加依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 vllm 和 transformers 到 dependencies**

在 `pyproject.toml` 的 `dependencies` 列表中添加：
```
"vllm>=0.8.0",
"transformers>=4.51.0",
```

- [ ] **Step 2: 安装依赖**

Run: `uv sync`
Expected: 成功安装

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add vllm and transformers dependencies"
```

---

### Task 5: 更新测试基础设施

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_chat.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 更新 conftest.py**

```python
"""共享测试配置和 fixtures."""

from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def is_llm_available() -> bool:
    """检查 LLM 是否可用."""
    try:
        from app.models.settings import get_chat_model

        model = get_chat_model()
        return model.is_available()
    except Exception:
        return False


SKIP_IF_NO_LLM = pytest.mark.skipif(
    not is_llm_available(),
    reason="LLM 不可用",
)
```

- [ ] **Step 2: 更新 test_chat.py — 使用 get_chat_model**

将 `ChatModel()` 直接构造改为通过 `get_chat_model()` 获取：

```python
"""聊天模型集成测试."""

from pathlib import Path

from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode
from tests.conftest import SKIP_IF_NO_LLM
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.state import AgentState


@SKIP_IF_NO_LLM
async def test_chat_drives_llm_memory_search(tmp_path: Path) -> None:
    """验证聊天驱动的 LLM 记忆搜索能检索到相关事件."""
    from app.models.settings import get_chat_model

    chat_model = get_chat_model()
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    await memory.write(MemoryEvent(content="明天下午三点项目会议", type="meeting"))
    results = await memory.search("有什么会议安排", mode=MemoryMode.MEMORY_BANK)
    assert len(results) > 0
    assert "会议" in results[0].event["content"]


@SKIP_IF_NO_LLM
async def test_chat_feeds_workflow_context(tmp_path: Path) -> None:
    """验证记忆上下文被注入到代理工作流状态中."""
    from app.agents.workflow import AgentWorkflow
    from app.models.settings import get_chat_model

    chat_model = get_chat_model()
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    await memory.write(MemoryEvent(content="下午三点开会", type="meeting"))
    workflow = AgentWorkflow(memory_module=memory)

    state: AgentState = {
        "messages": [{"role": "user", "content": "查一下会议"}],
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
    }
    result = await workflow._context_node(state)
    assert "related_events" in result["context"]
```

- [ ] **Step 3: 更新 test_settings.py — 添加 type 字段测试**

在 `TestLLMProviderConfig` 类中添加：

```python
def test_from_dict_with_type(self) -> None:
    """验证 type 字段正确解析."""
    cfg = LLMProviderConfig.from_dict(
        {
            "model": "Qwen/Qwen3.5-2B",
            "type": "vllm",
            "temperature": 0.7,
        }
    )
    assert cfg.type == "vllm"
    assert cfg.provider.model == "Qwen/Qwen3.5-2B"
```

在 `TestLLMSettingsLoad` 类中添加：

```python
def test_get_model_group_providers_vllm_type(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 vllm 类型 provider 正确解析 model 字段."""
    config_file = tmp_path / "llm.toml"
    config_file.write_text(
        tomli_w.dumps(
            {
                "model_groups": {"default": {"models": ["local/qwen3.5-2b"]}},
                "model_providers": {
                    "local": {
                        "type": "vllm",
                        "model": "Qwen/Qwen3.5-2B",
                        "tensor_parallel_size": 1,
                    },
                },
            }
        )
    )
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from adapters.model_config import _load_config

    _load_config.cache_clear()
    settings = LLMSettings.load()
    providers = settings.get_model_group_providers("default")
    assert len(providers) == 1
    assert providers[0].type == "vllm"
    assert providers[0].provider.model == "Qwen/Qwen3.5-2B"
    assert "tensor_parallel_size" in providers[0].extra
    _load_config.cache_clear()
```

- [ ] **Step 4: 运行 lint 和类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 5: 运行测试**

Run: `uv run pytest tests/test_settings.py tests/test_chat.py -v --timeout=30`
Expected: test_settings 全部通过，test_chat 因 LLM 不可用被跳过或通过

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_chat.py tests/test_settings.py
git commit -m "test: adapt tests for ChatModelProtocol and vLLM routing"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 完整 lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 2: 完整测试套件**

Run: `uv run pytest tests/ -v --timeout=120`
Expected: 非 LLM 测试全部通过，LLM 集成测试根据环境通过或跳过

- [ ] **Step 3: 验证 CI 配置一致性**

检查 `.github/workflows/python.yml` 中的命令与本地一致。
