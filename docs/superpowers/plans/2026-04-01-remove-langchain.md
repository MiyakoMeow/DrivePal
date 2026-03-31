# 移除 LangChain 生态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完全移除 LangChain/LangGraph 依赖，改用 openai SDK + sentence-transformers + 手写管道。

**Architecture:** ChatModel 用 openai.OpenAI 替换 ChatOpenAI；EmbeddingModel 用 sentence-transformers + openai SDK 替换 LangChain 封装；AgentWorkflow 用简单的 Pipeline 模式替换 StateGraph；消息格式从 BaseMessage 改为标准 dict。

**Tech Stack:** openai SDK, sentence-transformers, pydantic

**Spec:** `docs/superpowers/specs/2026-04-01-remove-langchain-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | 移除 langchain 依赖，新增 openai |
| `app/models/chat.py` | Rewrite | openai SDK 替换 ChatOpenAI |
| `app/models/embedding.py` | Rewrite | sentence-transformers + openai SDK |
| `app/agents/state.py` | Modify | BaseMessage → dict |
| `app/agents/workflow.py` | Rewrite | Pipeline 替换 StateGraph |
| `tests/test_chat.py` | Modify | 适配 dict 消息格式 |

---

### Task 1: 更新依赖（pyproject.toml）

**Files:**
- Modify: `pyproject.toml:7-20`

- [ ] **Step 1: 修改 pyproject.toml 依赖**

将：
```toml
dependencies = [
    "fastapi>=0.135.2",
    "uvicorn[standard]>=0.42.0",
    "langchain-core>=1.2.22",
    "langchain-openai>=1.1.12",
    "langgraph>=1.1.3",
    "langchain-community>=0.4.1",
    "pydantic>=2.12.5",
    "python-dotenv>=1.0.0",
    "datasets>=4.8.4",
    "huggingface-hub>=1.8.0",
    "sentence-transformers>=5.3.0",
    "langchain-huggingface>=1.2.1",
]
```

改为：
```toml
dependencies = [
    "fastapi>=0.135.2",
    "uvicorn[standard]>=0.42.0",
    "openai>=1.82.0",
    "pydantic>=2.12.5",
    "python-dotenv>=1.0.0",
    "datasets>=4.8.4",
    "huggingface-hub>=1.8.0",
    "sentence-transformers>=5.3.0",
]
```

- [ ] **Step 2: 同步依赖**

Run: `uv sync`
Expected: 成功安装 openai，移除 langchain 相关包

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: replace langchain deps with openai sdk"
```

---

### Task 2: 重写 ChatModel（app/models/chat.py）

**Files:**
- Rewrite: `app/models/chat.py`

- [ ] **Step 1: 重写 chat.py**

完整替换为：

```python
"""LLM对话模型封装，基于openai SDK，支持多provider自动fallback."""

from collections.abc import AsyncIterator
from typing import Optional

import openai

from app.models.settings import LLMProviderConfig, LLMSettings


class ChatModel:
    """LLM对话模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[LLMProviderConfig] | None = None,
        temperature: float | None = None,
    ) -> None:
        """初始化对话模型."""
        if providers is None:
            settings = LLMSettings.load()
            providers = settings.llm_providers
        if not providers:
            raise RuntimeError("No LLM providers configured")
        self.providers = providers
        self.temperature = temperature

    def _create_client(self, provider: LLMProviderConfig) -> openai.OpenAI:
        kwargs: dict = {
            "api_key": provider.provider.api_key or "not-needed",
        }
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.OpenAI(**kwargs)

    def _create_async_client(
        self, provider: LLMProviderConfig,
    ) -> openai.AsyncOpenAI:
        kwargs: dict = {
            "api_key": provider.provider.api_key or "not-needed",
        }
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.AsyncOpenAI(**kwargs)

    def _build_messages(
        self, prompt: str, system_prompt: Optional[str] = None,
    ) -> list[dict]:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _get_temperature(self, provider: LLMProviderConfig) -> float:
        return (
            self.temperature
            if self.temperature is not None
            else provider.temperature
        )

    def generate(
        self, prompt: str, system_prompt: Optional[str] = None, **_kwargs: object,
    ) -> str:
        """生成回复，按 provider 顺序尝试，失败自动 fallback."""
        messages = self._build_messages(prompt, system_prompt)

        errors = []
        for provider in self.providers:
            try:
                client = self._create_client(provider)
                response = client.chat.completions.create(
                    model=provider.provider.model,
                    messages=messages,
                    temperature=self._get_temperature(provider),
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    async def generate_stream(
        self, prompt: str, system_prompt: Optional[str] = None, **_kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复，按 provider 顺序尝试，失败自动 fallback."""
        messages = self._build_messages(prompt, system_prompt)

        errors = []
        for provider in self.providers:
            try:
                client = self._create_async_client(provider)
                stream = await client.chat.completions.create(
                    model=provider.provider.model,
                    messages=messages,
                    temperature=self._get_temperature(provider),
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
                return
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    def batch_generate(
        self, prompts: list[str], system_prompt: Optional[str] = None,
    ) -> list[str]:
        """批量生成."""
        return [self.generate(p, system_prompt) for p in prompts]
```

- [ ] **Step 2: 运行 lint 和类型检查**

Run: `uv run ruff check --fix app/models/chat.py && uv run ruff format app/models/chat.py && uv run ty check app/models/chat.py`

- [ ] **Step 3: Commit**

```bash
git add app/models/chat.py
git commit -m "refactor: rewrite ChatModel with openai SDK"
```

---

### Task 3: 重写 EmbeddingModel（app/models/embedding.py）

**Files:**
- Rewrite: `app/models/embedding.py`

- [ ] **Step 1: 重写 embedding.py**

完整替换为：

```python
"""文本嵌入模型封装，支持 HuggingFace 本地模型和 OpenAI 兼容远程接口."""

from typing import Any, Optional, Union

import openai

from app.models.settings import EmbeddingProviderConfig, LLMSettings, ProviderConfig

_EMBEDDING_MODEL_CACHE: dict[str, "EmbeddingModel"] = {}


def get_cached_embedding_model(device: str | None = None) -> "EmbeddingModel":
    """获取缓存的 embedding 模型实例，避免重复加载."""
    cache_key = f"device={device or 'default'}"
    if cache_key not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(device=device)
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """清除 embedding 模型缓存."""
    _EMBEDDING_MODEL_CACHE.clear()


class EmbeddingModel:
    """文本嵌入模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[EmbeddingProviderConfig] | None = None,
        device: str | None = None,
    ) -> None:
        """初始化嵌入模型."""
        if providers is None:
            try:
                settings = LLMSettings.load()
                providers = settings.embedding_providers
            except RuntimeError:
                providers = [
                    EmbeddingProviderConfig(
                        provider=ProviderConfig(model="BAAI/bge-small-zh-v1.5"),
                        device=device or "cpu",
                    )
                ]
        self.providers = providers
        self.device = device
        self._client: Union[openai.OpenAI, Any, None] = None

    @property
    def client(self) -> Union[openai.OpenAI, Any]:
        """获取或延迟创建嵌入模型客户端，按 provider 顺序尝试."""
        if self._client is not None:
            return self._client

        if not self.providers:
            raise RuntimeError("No embedding providers configured")

        errors = []
        for provider in self.providers:
            try:
                self._client = self._create_client(provider)
                return self._client
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise RuntimeError(f"All embedding providers failed: {'; '.join(errors)}")

    def _create_client(
        self, provider: EmbeddingProviderConfig,
    ) -> Union[openai.OpenAI, Any]:
        device = self.device or provider.device
        if provider.provider.base_url:
            kwargs: dict[str, Any] = {"api_key": provider.provider.api_key or "not-needed"}
            kwargs["base_url"] = provider.provider.base_url
            return openai.OpenAI(**kwargs)
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(
            provider.provider.model,
            device=device,
        )

    def _encode_with_openai(
        self, client: openai.OpenAI, model: str, text: str,
    ) -> list[float]:
        resp = client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    def _encode_with_local(
        self, model: Any, text: str,
    ) -> list[float]:
        return model.encode(text, normalize_embeddings=True).tolist()

    def _batch_encode_with_openai(
        self, client: openai.OpenAI, model: str, texts: list[str],
    ) -> list[list[float]]:
        resp = client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]

    def _batch_encode_with_local(
        self, model: Any, texts: list[str],
    ) -> list[list[float]]:
        embeddings = model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    def _find_provider(self) -> EmbeddingProviderConfig:
        if not self.providers:
            raise RuntimeError("No embedding providers configured")
        return self.providers[0]

    def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        cl = self.client
        provider = self._find_provider()
        if provider.provider.base_url:
            return self._encode_with_openai(cl, provider.provider.model, text)
        return self._encode_with_local(cl, text)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码."""
        cl = self.client
        provider = self._find_provider()
        if provider.provider.base_url:
            return self._batch_encode_with_openai(cl, provider.provider.model, texts)
        return self._batch_encode_with_local(cl, texts)
```

- [ ] **Step 2: 运行 lint 和类型检查**

Run: `uv run ruff check --fix app/models/embedding.py && uv run ruff format app/models/embedding.py && uv run ty check app/models/embedding.py`

- [ ] **Step 3: Commit**

```bash
git add app/models/embedding.py
git commit -m "refactor: rewrite EmbeddingModel with openai SDK and sentence-transformers"
```

---

### Task 4: 修改 AgentState（app/agents/state.py）

**Files:**
- Modify: `app/agents/state.py`

- [ ] **Step 1: 修改 state.py**

完整替换为：

```python
"""Agent状态定义模块."""

from typing import Optional, TypedDict

from app.memory.types import MemoryMode


class AgentState(TypedDict):
    """Agent状态定义."""

    messages: list[dict]
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    memory_mode: "MemoryMode"
    result: Optional[str]
    event_id: Optional[str]
```

- [ ] **Step 2: 运行 lint 和类型检查**

Run: `uv run ruff check --fix app/agents/state.py && uv run ruff format app/agents/state.py && uv run ty check app/agents/state.py`

- [ ] **Step 3: Commit**

```bash
git add app/agents/state.py
git commit -m "refactor: replace BaseMessage with dict in AgentState"
```

---

### Task 5: 重写 AgentWorkflow（app/agents/workflow.py）

**Files:**
- Rewrite: `app/agents/workflow.py`

- [ ] **Step 1: 重写 workflow.py**

完整替换为：

```python
"""Agent工作流编排模块."""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.agents.state import AgentState
from app.agents.prompts import SYSTEM_PROMPTS
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.storage.json_store import JSONStore

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """多Agent协作工作流."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
        memory_module: Optional[MemoryModule] = None,
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self.memory_mode = memory_mode

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            from app.models.settings import get_chat_model

            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self.memory_module.set_default_mode(memory_mode)

        self._nodes = [
            self._context_node,
            self._task_node,
            self._strategy_node,
            self._execution_node,
        ]

    def _call_llm_json(self, user_prompt: str) -> dict:
        """构建 prompt、调 LLM 并解析 JSON 返回 dict."""
        if not self.memory_module.chat_model:
            raise RuntimeError("ChatModel not available")
        result = self.memory_module.chat_model.generate(user_prompt)
        cleaned = re.sub(r"^```(?:json)?\s*", "", result.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                parsed = {"raw": result}
        except json.JSONDecodeError:
            parsed = {"raw": result}
        parsed["raw"] = result
        return parsed

    def _context_node(self, state: AgentState) -> dict:
        """Context Agent节点."""
        messages = state.get("messages", [])
        if not messages:
            user_input = ""
        else:
            user_input = str(messages[-1].get("content", ""))

        try:
            related_events = (
                self.memory_module.search(user_input, mode=self.memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            related_events = []

        try:
            if related_events:
                relevant_memories = [e.to_public() for e in related_events]
            else:
                relevant_memories = [
                    e.model_dump() for e in self.memory_module.get_history()
                ]
        except ValueError as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )
        except Exception as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )

        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SYSTEM_PROMPTS["context"].format(
            current_datetime=current_datetime
        )

        prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

        context = self._call_llm_json(prompt)
        context["related_events"] = relevant_memories
        context["relevant_memories"] = relevant_memories

        return {
            "context": context,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Context: {json.dumps(context)}"}],
        }

    def _task_node(self, state: AgentState) -> dict:
        """Task Agent节点."""
        messages = state.get("messages", [])
        user_input = messages[-1].get("content", "") if messages else ""
        context = state.get("context", {})

        prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象. """

        task = self._call_llm_json(prompt)
        return {
            "task": task,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Task: {json.dumps(task)}"}],
        }

    def _strategy_node(self, state: AgentState) -> dict:
        """Strategy Agent节点."""
        context = state.get("context", {})
        task = state.get("task", {})

        strategies = JSONStore(self.data_dir, Path("strategies.json"), dict).read()

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}

请输出JSON格式的决策结果. """

        decision = self._call_llm_json(prompt)
        return {
            "decision": decision,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Decision: {json.dumps(decision)}"}],
        }

    def _execution_node(self, state: AgentState) -> dict:
        """执行提醒动作的Agent节点."""
        decision = state.get("decision") or {}
        messages = state.get("messages", [])
        user_input = str(messages[0].get("content", "")) if messages else ""

        remind_content = decision.get("reminder_content") or decision.get(
            "remind_content"
        )
        if isinstance(remind_content, dict):
            content = remind_content.get("text") or remind_content.get(
                "content", "无提醒内容"
            )
        elif isinstance(remind_content, str):
            content = remind_content
        else:
            content = decision.get("content") or "无提醒内容"
        event_id = self.memory_module.write_interaction(user_input, content)
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"

        result = f"提醒已发送: {content}"
        return {
            "result": result,
            "event_id": event_id,
            "messages": state["messages"]
            + [{"role": "user", "content": result}],
        }

    def run(self, user_input: str) -> tuple[str, Optional[str]]:
        """运行完整工作流并返回结果和事件ID."""
        state: AgentState = {
            "messages": [{"role": "user", "content": user_input}],
            "context": {},
            "task": {},
            "decision": {},
            "memory_mode": self.memory_mode,
            "result": None,
            "event_id": None,
        }

        for node_fn in self._nodes:
            updates = node_fn(state)
            state.update(updates)

        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id


def create_workflow(
    data_dir: Path = Path("data"), memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
) -> AgentWorkflow:
    """创建工作流实例."""
    return AgentWorkflow(data_dir, memory_mode)
```

- [ ] **Step 2: 运行 lint 和类型检查**

Run: `uv run ruff check --fix app/agents/workflow.py && uv run ruff format app/agents/workflow.py && uv run ty check app/agents/workflow.py`

- [ ] **Step 3: Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: replace StateGraph with simple pipeline in AgentWorkflow"
```

---

### Task 6: 更新测试（tests/test_chat.py）

**Files:**
- Modify: `tests/test_chat.py`

- [ ] **Step 1: 修改 test_chat.py**

将第 24-43 行的 `test_chat_feeds_workflow_context` 函数替换为：

```python
@SKIP_IF_NO_LLM
def test_chat_feeds_workflow_context(tmp_path: Path) -> None:
    """验证记忆上下文被注入到代理工作流状态中."""
    from app.agents.workflow import AgentWorkflow
    from app.agents.state import AgentState

    memory = MemoryModule(tmp_path, chat_model=ChatModel())
    memory.write(MemoryEvent(content="下午三点开会", type="meeting"))
    workflow = AgentWorkflow(memory_module=memory)

    state: AgentState = {
        "messages": [{"role": "user", "content": "查一下会议"}],
        "context": {},
        "task": None,
        "decision": None,
        "memory_mode": MemoryMode.MEMORY_BANK,
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert "related_events" in result["context"]
```

即：
- 删除 `from langchain_core.messages import HumanMessage` 导入
- `HumanMessage(content="查一下会议")` → `{"role": "user", "content": "查一下会议"}`

- [ ] **Step 2: 运行 lint**

Run: `uv run ruff check --fix tests/test_chat.py && uv run ruff format tests/test_chat.py`

- [ ] **Step 3: Commit**

```bash
git add tests/test_chat.py
git commit -m "test: adapt test to dict message format"
```

---

### Task 7: 全局验证

- [ ] **Step 1: 全局搜索确认无残留 langchain 导入**

Run: `rg "from langchain|import langchain|from langgraph|import langgraph" app/ tests/ --type py`
Expected: 无匹配

- [ ] **Step 2: 全量 lint + 类型检查**

Run: `uv run ruff check --fix && uv run ruff format && uv run ty check`
Expected: 全部通过

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/ -v`
Expected: 全部通过（集成测试可能因无 LLM 配置被跳过，这是正常的）

- [ ] **Step 4: Commit**

如有 lint 自动修复：
```bash
git add -A && git commit -m "chore: final cleanup after langchain removal"
```
