# 非记忆模块重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复非记忆系统 4 个模块层的 12 个问题（JSONL 存储、规则硬约束、死代码清理、API 简化）

**架构：** 4 批次按依赖顺序实施：storage(底层) → models(独立) → agents(依赖前两者) → api(依赖全部)

**技术栈：** Python 3.14 + aiofiles + tomli_w + strawberry-graphql

---

## 文件总览

### 新建
- `app/storage/jsonl_store.py` — JSON Lines 追加写存储

### 修改
- `app/storage/init_data.py` — 替换 events/feedback/interactions 为 .jsonl
- `app/storage/__init__.py` — 导出 JSONLinesStore
- `app/memory/components.py` — FeedbackManager 改用 JSONLinesStore 存 feedback
- `app/models/model_string.py` — 删除死函数 get_model_group_providers
- `app/models/chat.py` — 暴露 semaphore_cache 用于测试清理
- `app/models/embedding.py` — 简化后台任务关闭
- `app/agents/rules.py` — 新增 postprocess_decision
- `app/agents/workflow.py` — 硬约束 + JSON mode + 提取内容改进
- `app/api/resolvers/mutation.py` — DRY 异常 + pydantic 映射
- `app/api/graphql_schema.py` — pydantic 集成类型
- `tests/fixtures.py` — 新增 semaphore 缓存清理
- `tests/test_storage.py` — 适配 JSONL

### 不变（用 TOMLStore 但无需改动）
- `app/agents/workflow.py` → `strategies.toml`（保持 TOML）
- `app/api/resolvers/mutation.py` → `scenario_presets.toml`（保持 TOML）
- `app/memory/components.py` → `strategies.toml`（保持 TOML）

---

## Batch 1: Storage — JSON Lines 迁移

### 任务 1.1：实现 JSONLinesStore

**文件：**
- 创建：`app/storage/jsonl_store.py`
- 测试：`tests/test_storage.py`（追加测试）

- [ ] **步骤 1：编写 JSONLinesStore 接口和测试**

```python
# tests/test_storage.py — 追加到文件末尾
import json
from app.storage.jsonl_store import JSONLinesStore


class TestJSONLinesStore:
    """JSONLinesStore 单元测试."""

    async def test_append_and_read(self, tmp_path: Path) -> None:
        s = JSONLinesStore(tmp_path / "test.jsonl")
        await s.append({"a": 1})
        await s.append({"b": 2})
        items = await s.read_all()
        assert len(items) == 2
        assert items[0] == {"a": 1}

    async def test_count(self, tmp_path: Path) -> None:
        s = JSONLinesStore(tmp_path / "test.jsonl")
        await s.append({"x": 1})
        assert await s.count() == 1

    async def test_read_empty_file(self, tmp_path: Path) -> None:
        s = JSONLinesStore(tmp_path / "test.jsonl")
        items = await s.read_all()
        assert items == []

    async def test_append_empty_object(self, tmp_path: Path) -> None:
        s = JSONLinesStore(tmp_path / "test.jsonl")
        await s.append({})
        items = await s.read_all()
        assert items == [{}]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest tests/test_storage.py::TestJSONLinesStore -v`
预期：4 FAIL（模块未找到）

- [ ] **步骤 3：实现 JSONLinesStore**

```python
# app/storage/jsonl_store.py
"""JSON Lines 追加写存储，支持异步读写."""

import json
import logging
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


class JSONLinesStore:
    """JSON Lines 文件存储，追加写 O(1)，进程安全（O_APPEND）。"""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath

    async def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            async with aiofiles.open(self.filepath, "w") as f:
                pass  # 创建空文件

    async def append(self, obj: dict[str, Any]) -> None:
        """追加写入一条 JSON 对象（新行）。"""
        await self._ensure_file()
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        async with aiofiles.open(self.filepath, "a", encoding="utf-8") as f:
            await f.write(line)

    async def read_all(self) -> list[dict[str, Any]]:
        """读取所有行，每行解析为 dict。文件不存在或为空返回 []。"""
        if not self.filepath.exists():
            return []
        result: list[dict[str, Any]] = []
        async with aiofiles.open(self.filepath, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning("Skipping invalid JSON line: %s", e)
        return result

    async def count(self) -> int:
        """返回文件行数（近似于记录数）。"""
        if not self.filepath.exists():
            return 0
        count = 0
        async with aiofiles.open(self.filepath, "r", encoding="utf-8") as f:
            async for _ in f:
                count += 1
        return count
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest tests/test_storage.py::TestJSONLinesStore -v`
预期：4 PASS

- [ ] **步骤 5：导出 JSONLinesStore**

```python
# app/storage/__init__.py — 修改
from app.storage.jsonl_store import JSONLinesStore
from app.storage.toml_store import TOMLStore

__all__ = ["JSONLinesStore", "TOMLStore"]
```

- [ ] **步骤 6：Commit**

```bash
git add app/storage/jsonl_store.py app/storage/__init__.py tests/test_storage.py
git commit -m "feat(storage): add JSONLinesStore for append-only O(1) writes"
```


### 任务 1.2：更新 init_data.py + FeedbackManager

**文件：**
- 修改：`app/storage/init_data.py`
- 修改：`app/memory/components.py`

- [ ] **步骤 1：修改 init_data.py**

将 events/feedback/interactions 从 `.toml` 改为 `.jsonl`，移除 `memorybank_summaries.toml`（未使用）。

```python
# app/storage/init_data.py — 修改 init_storage
def init_storage(data_dir: Path | None = None) -> None:
    if data_dir is None:
        data_dir = get_data_dir()
    data_dir.mkdir(exist_ok=True)

    jsonl_files = [
        "events.jsonl",
        "interactions.jsonl",
        "feedback.jsonl",
        "experiment_results.jsonl",
    ]

    dict_files = {
        "contexts.toml": {},
        "preferences.toml": {"language": "zh-CN"},
        "strategies.toml": {
            "preferred_time_offset": 15,
            "preferred_method": "visual",
            "reminder_weights": {},
            "ignored_patterns": [],
            "modified_keywords": [],
            "cooldown_periods": {},
        },
    }

    for filename in jsonl_files:
        filepath = data_dir / filename
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text("", encoding="utf-8")

    for filename, default_data in dict_files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            with filepath.open("wb") as f:
                import tomli_w
                tomli_w.dump(default_data, f)
```

- [ ] **步骤 2：修改 FeedbackManager 改用 JSONLinesStore**

```python
# app/memory/components.py — 修改 __init__ 和方法
from app.storage.jsonl_store import JSONLinesStore
from app.storage.toml_store import TOMLStore

class FeedbackManager:
    def __init__(self, data_dir: Path) -> None:
        self._strategies_store = TOMLStore(data_dir, Path("strategies.toml"), dict)
        self._feedback_store = JSONLinesStore(data_dir / "feedback.jsonl")

    @property
    def strategies_store(self) -> TOMLStore:
        return self._strategies_store

    async def _append_feedback(self, record: dict) -> None:
        await self._feedback_store.append(record)
```

- [ ] **步骤 3：运行现有测试，确认未破坏**

运行：`uv run pytest tests/test_components.py -v`
预期：PASS（或跳过，因 embedding marker）

运行：`uv run ruff check --fix`
预期：All checks passed

- [ ] **步骤 4：Commit**

```bash
git add app/storage/init_data.py app/memory/components.py
git commit -m "refactor(storage): replace events/feedback/interactions TOML files with JSONL"
```


## Batch 3: Models — 死代码 + 资源管理

### 任务 3.1：删除死函数 get_model_group_providers

**文件：**
- 修改：`app/models/model_string.py`

- [ ] **步骤 1：确认无调用方**

运行：`rg "get_model_group_providers" app/ tests/`
预期：仅出现在 `model_string.py` 自身定义处

- [ ] **步骤 2：删除函数**

```python
# app/models/model_string.py — 删除以下函数及关联注释
# def get_model_group_providers(name: str) -> list[dict]:
#     """按组名获取 LLMProviderConfig 字典列表（底层接口）. ..."""
# 删除整个函数（约 42 行）
```

同时删除已无用的导入：
```python
# 删除不再需要的：
# from app.models.exceptions import ModelGroupNotFoundError, ProviderNotFoundError
```
但需确认 `resolve_model_string` 中是否还用到 `ProviderNotFoundError`（是 —— `_resolve_provider` 中用到了）。保留 `ProviderNotFoundError`，只删 `ModelGroupNotFoundError` 导入。

实际 `model_string.py` 的 import:
```python
from app.models.exceptions import ModelGroupNotFoundError, ProviderNotFoundError
```
删除 `ModelGroupNotFoundError` 的导入（不再使用）。

- [ ] **步骤 3：运行 lint 确认**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：All checks passed

- [ ] **步骤 4：Commit**

```bash
git add app/models/model_string.py
git commit -m "refactor(models): remove dead get_model_group_providers function"
```


### 任务 3.2：修复 ChatModel semaphore 缓存泄漏

**文件：**
- 修改：`tests/fixtures.py`
- 修改：`app/models/chat.py`（暴露清理接口）

- [ ] **步骤 1：暴露 semaphore 清理函数**

```python
# app/models/chat.py — 添加模块级清理函数
def clear_semaphore_cache() -> None:
    """清理 provider semaphore 缓存（供测试使用）。"""
    _semaphore_cache.clear()
    _get_lock.cache_clear()
```

- [ ] **步骤 2：fixtures.py 中调用**

```python
# tests/fixtures.py
import app.models.chat
from app.models.chat import clear_semaphore_cache

def reset_all_singletons() -> None:
    reset_embedding_singleton()
    with suppress(AttributeError):
        LLMSettings.load.cache_clear()
    with suppress(AttributeError):
        clear_semaphore_cache()
    with suppress(AttributeError):
        app.memory.singleton._memory_module_state[0] = None
```

已去除 `app.models.chat._get_lock.cache_clear()` 和 `app.models.chat._semaphore_cache.clear()` —— 现在调用 `clear_semaphore_cache()`。

- [ ] **步骤 3：运行 lint 确认**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：OK

- [ ] **步骤 4：Commit**

```bash
git add tests/fixtures.py app/models/chat.py
git commit -m "refactor(models): expose semaphore cache cleanup for test isolation"
```


### 任务 3.3：简化 EmbeddingModel 后台任务

**文件：**
- 修改：`app/models/embedding.py`

- [ ] **步骤 1：简化 clear_embedding_model_cache**

```python
# app/models/embedding.py — 修改 clear_embedding_model_cache
def clear_embedding_model_cache() -> None:
    """关闭所有缓存的客户端并清除缓存。同步关闭，不再创建后台 task。"""
    if not _EMBEDDING_MODEL_CACHE:
        return
    models = list(_EMBEDDING_MODEL_CACHE.values())
    _EMBEDDING_MODEL_CACHE.clear()
    for model in models:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(model.aclose())
            else:
                asyncio.run(model.aclose())
        except RuntimeError:
            asyncio.run(model.aclose())
```

删除不再需要的：
```python
# 删除
_background_tasks: set[asyncio.Task[None]] = set()

def _finalize_background_task(task: asyncio.Task[None]) -> None:
    ...
```

同时确保 `clear_embedding_model_cache` 在循环有 `async with` 上下文时不崩。使用 `contextlib.suppress(RuntimeError)` 兜底。

- [ ] **步骤 2：运行 lint 确认**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：OK

- [ ] **步骤 3：Commit**

```bash
git add app/models/embedding.py
git commit -m "refactor(models): simplify embedding cache cleanup, remove background task set"
```


## Batch 2: Agents — 规则硬约束 + Workflow

### 任务 2.1：新增 postprocess_decision

**文件：**
- 修改：`app/agents/rules.py`
- 测试：`tests/test_rules.py`

- [ ] **步骤 1：编写测试**

```python
# tests/test_rules.py — 追加
from app.agents.rules import postprocess_decision


class TestPostprocessDecision:
    """规则后处理测试."""

    def test_postpone_overrides_decision(self) -> None:
        """postpone=True → should_remind=false, reminder_content 置空."""
        ctx = {
            "driver": {"workload": "overloaded"},
            "scenario": "city_driving",
        }
        decision = {
            "should_remind": True,
            "reminder_content": "提醒事项",
            "allowed_channels": ["visual", "audio"],
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False
        assert result["reminder_content"] == ""

    def test_allowed_channels_filtered(self) -> None:
        """allowed_channels 被安全规则过滤."""
        ctx = {
            "driver": {"fatigue_level": 0.0, "workload": "low"},
            "scenario": "highway",
        }
        decision = {
            "should_remind": True,
            "reminder_content": "前方出口",
            "allowed_channels": ["visual", "audio", "detailed"],
        }
        result = postprocess_decision(decision, ctx)
        assert result["allowed_channels"] == ["audio"]

    def test_only_urgent_blocks_non_urgent(self) -> None:
        """only_urgent=True 且 type=general → should_remind=false."""
        ctx = {
            "driver": {"fatigue_level": 0.8, "workload": "normal"},
            "scenario": "city_driving",
        }
        decision = {
            "should_remind": True,
            "reminder_content": "普通提醒",
            "type": "general",
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is False

    def test_only_urgent_allows_urgent_types(self) -> None:
        """only_urgent=True 但 type=warning → 正常通过."""
        ctx = {
            "driver": {"fatigue_level": 0.8, "workload": "normal"},
            "scenario": "city_driving",
        }
        decision = {
            "should_remind": True,
            "reminder_content": "油量不足",
            "type": "warning",
        }
        result = postprocess_decision(decision, ctx)
        assert result["should_remind"] is True
```

- [ ] **步骤 2：实现 postprocess_decision**

```python
# app/agents/rules.py — 新增函数
URGENT_TYPES = frozenset({"warning", "safety", "alert"})

def postprocess_decision(decision: dict, driving_context: dict) -> dict:
    """在 LLM 决策后强制应用安全规则，不可绕过。

    Args:
        decision: LLM 输出的决策 dict。
        driving_context: 当前驾驶上下文。

    Returns:
        规则强制覆盖后的 decision。

    """
    result = dict(decision)
    constraints = apply_rules(driving_context)

    # 硬约束 1：postpone → 禁止发送
    if constraints.get("postpone", False):
        result["should_remind"] = False
        result["reminder_content"] = ""

    # 硬约束 2：allowed_channels 过滤
    allowed = constraints.get("allowed_channels", [])
    if allowed:
        channels = result.get("allowed_channels", allowed)
        if isinstance(channels, list):
            filtered = [c for c in channels if c in allowed]
            result["allowed_channels"] = filtered or allowed

    # 硬约束 3：only_urgent → 非紧急类型禁止
    if constraints.get("only_urgent", False):
        event_type = result.get("type", "general")
        if event_type not in URGENT_TYPES:
            result["should_remind"] = False
            result["reminder_content"] = ""

    return result
```

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/test_rules.py -v`
预期：所有测试 PASS（含旧的 + 新的）

- [ ] **步骤 4：Commit**

```bash
git add app/agents/rules.py tests/test_rules.py
git commit -m "feat(agents): add postprocess_decision for hard safety constraints"
```


### 任务 2.2：Workflow 集成硬约束 + 改进 LLM JSON 解析

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：修改 _execution_node，执行前调用 postprocess_decision**

```python
# app/agents/workflow.py — 改动 _execution_node
from app.agents.rules import postprocess_decision

class AgentWorkflow:
    ...
    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        stages = state.get("stages")

        # 规则硬约束：LLM 决策后强制覆盖
        driving_ctx = state.get("driving_context")
        if driving_ctx:
            decision = postprocess_decision(decision, driving_ctx)

        postpone = decision.get("postpone", False)
        if postpone:
            result = "提醒已延后：当前驾驶状态不适合发送提醒"
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": result,
                }
            return {"result": result, "event_id": None}

        content = self._extract_content(decision)
        original_query = state.get("original_query", "")
        interaction_result = await self.memory_module.write_interaction(
            original_query, content, mode=self._memory_mode,
        )
        event_id = interaction_result.event_id
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = f"unknown_{hashlib.sha256(str(decision).encode()).hexdigest()[:8]}"

        result = f"提醒已发送: {content}"
        if stages is not None:
            stages.execution = {
                "content": content,
                "event_id": event_id,
                "result": result,
            }
        return {"result": result, "event_id": event_id}
```

注意：`_strategy_node` 中的 `postpone` 字段仍用于 prompt，但 `_execution_node` 中强制覆盖是最终裁决。

- [ ] **步骤 2：改进 _call_llm_json 支持 JSON mode**

```python
# app/agents/workflow.py — 修改 _call_llm_json
async def _call_llm_json(self, user_prompt: str) -> LLMJsonResponse:
    if not self.memory_module.chat_model:
        raise ChatModelUnavailableError
    # 优先使用 JSON mode（结构化输出）
    result = await self.memory_module.chat_model.generate(
        user_prompt,
        json_mode=True,  # 假设 ChatModel.generate 支持此参数
    )
    return LLMJsonResponse.from_llm(result)
```

**需验证 ChatModel.generate 是否接受 json_mode 参数。** 当前 `generate` 签名：
```python
async def generate(self, prompt, system_prompt=None, **_kwargs):
```
已有 `**_kwargs` 消费额外参数。但 OpenAI API 需 response_format 参数。改 ChatModel.generate 在 `json_mode=True` 时传入 `response_format={"type": "json_object"}`。

```python
# app/models/chat.py — 改动 generate 方法
async def generate(
    self,
    prompt: str,
    system_prompt: str | None = None,
    json_mode: bool = False,
    **_kwargs: object,
) -> str:
    messages = self._build_messages(prompt, system_prompt)
    errors = []
    for provider in self.providers:
        sem = await self._acquire_slot(provider)
        try:
            async with sem, self._create_client(provider) as client:
                kwargs: dict = {
                    "model": provider.provider.model,
                    "messages": messages,
                    "temperature": self._get_temperature(provider),
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = await client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
```

注意：需 import `openai` 以检查 `APIError` 子类等。已有。

- [ ] **步骤 3：改进 _extract_content 用 Pydantic**

```python
# app/agents/workflow.py — 替换 _extract_content
from pydantic import BaseModel

class ReminderContent(BaseModel):
    """提醒内容校验模型."""
    text: str = ""
    content: str = ""

    @classmethod
    def from_decision(cls, decision: dict) -> str:
        for key in ("reminder_content", "remind_content", "content"):
            val = decision.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                return val.get("text") or val.get("content") or ""
        return "无提醒内容"
```

`_extract_content` 改为调用 `ReminderContent.from_decision(decision)`。

- [ ] **步骤 4：运行 lint + 类型检查**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：All checks passed

- [ ] **步骤 5：Commit**

```bash
git add app/agents/workflow.py app/models/chat.py
git commit -m "feat(agents): hard safety constraints, JSON mode support, robust content extraction"
```


## Batch 4: API — DRY 异常 + GQL 映射简化

### 任务 4.1：DRY 异常处理

**文件：**
- 修改：`app/api/resolvers/mutation.py`

- [ ] **步骤 1：提取 _safe_memory_call 辅助函数**

```python
# app/api/resolvers/mutation.py — 新增辅助函数
import logging
from collections.abc import Awaitable
from typing import TypeVar

from graphql.error import GraphQLError

T = TypeVar("T")

logger = logging.getLogger(__name__)

async def _safe_memory_call(
    coro: Awaitable[T],
    context_msg: str,
    error_map: dict[type, str] | None = None,
) -> T:
    """执行记忆系统调用，异常统一转为 GraphQLError.

    Args:
        coro: 待执行的异步调用。
        context_msg: 异常日志上下文描述。
        error_map: 异常类型 → 用户可见错误消息映射。

    Returns:
        调用结果。

    Raises:
        GraphQLError: 所有记忆层异常包装后抛出。

    """
    if error_map is None:
        error_map = {
            OSError: "Internal storage error",
            RuntimeError: "Internal runtime error",
            ValueError: "Invalid data",
        }
    try:
        return await coro
    except GraphQLError:
        raise
    except tuple(error_map) as e:
        msg = error_map.get(type(e), "Internal server error")
        logger.exception("%s failed: %s", context_msg, e)
        raise GraphQLError(str(msg)) from e  # ty: ignore[misc]
    except Exception as e:
        logger.exception("%s failed: %s", context_msg, e)
        raise InternalServerError from e
```

- [ ] **步骤 2：简化 submit_feedback**

```python
# app/api/resolvers/mutation.py — 替换 submit_feedback 中两个 try 块

@strawberry.mutation
async def submit_feedback(
    self,
    feedback_input: Annotated[FeedbackInput, strawberry.argument(name="input")],
) -> FeedbackResult:
    if feedback_input.action not in ("accept", "ignore"):
        raise GraphQLInvalidActionError(feedback_input.action)

    mm = get_memory_module()
    safe_action: Literal["accept", "ignore"]
    safe_action = "accept" if feedback_input.action == "accept" else "ignore"
    mode = MemoryMode(feedback_input.memory_mode.value)

    actual_type = await _safe_memory_call(
        mm.get_event_type(feedback_input.event_id, mode=mode),
        "submitFeedback(get_event_type)",
    )

    if actual_type is None:
        raise GraphQLEventNotFoundError(feedback_input.event_id)

    feedback = FeedbackData(
        action=safe_action,
        type=actual_type,
        modified_content=feedback_input.modified_content,
    )
    await _safe_memory_call(
        mm.update_feedback(feedback_input.event_id, feedback, mode=mode),
        "submitFeedback(update_feedback)",
    )
    return FeedbackResult(status="success")
```

- [ ] **步骤 3：运行 lint 确认**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：All checks passed

- [ ] **步骤 4：运行 graphql 测试**

运行：`uv run pytest tests/test_graphql.py -v`
预期：测试通过（无 embedding/llm marker 的）或跳过

- [ ] **步骤 5：Commit**

```bash
git add app/api/resolvers/mutation.py
git commit -m "refactor(api): DRY exception handling via _safe_memory_call helper"
```


### 任务 4.2：简化 GQL-Pydantic 类型映射

**文件：**
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/mutation.py`

- [ ] **步骤 1：确认 strawberry.experimental.pydantic API**

运行：`uv run python -c "
import inspect
from strawberry.experimental.pydantic import type as pydantic_type
from app.schemas.context import DrivingContext
T = pydantic_type(DrivingContext)
# 确认生成类型的方法签名
methods = [m for m in dir(T) if not m.startswith('_')]
print('Generated methods:', methods)
print('from_pydantic' in methods or 'from_instance' in methods)
"`
预期：OK，确认 `from_pydantic` 或 `from_instance` 方法存在

- [ ] **步骤 2：使用 pydantic 集成生成 GQL 类型**

```python
# app/api/graphql_schema.py — 替换手写 GQL 类型
import strawberry
from strawberry.experimental.pydantic import type as pydantic_type

from app.schemas.context import (
    DriverState as DriverStateModel,
    DrivingContext as DrivingContextModel,
    GeoLocation as GeoLocationModel,
    SpatioTemporalContext as SpatioTemporalContextModel,
    TrafficCondition as TrafficConditionModel,
)

# 移除所有手写 GQL 输出类型，改为自动生成
DriverStateGQL = pydantic_type(DriverStateModel)
GeoLocationGQL = pydantic_type(GeoLocationModel)
SpatioTemporalContextGQL = pydantic_type(SpatioTemporalContextModel)
TrafficConditionGQL = pydantic_type(TrafficConditionModel)
DrivingContextGQL = pydantic_type(DrivingContextModel)
```

注意：`pydantic_type` 生成的类型默认使用 Pydantic 字段名。对于纯输出类型这足够。

输入类型仍需手写（Strawberry experimental pydantic input 可能不支持复杂 Literal 映射），或保留现有 input 类型。

**需验证：** pydantic_type 如何处理 `Literal["neutral", ...]` 字段。如果生成 GQL Enum，需手动映射到现有的 `EmotionEnum`/`WorkloadEnum` 等。可能需保留部分手写类型。

调整方案：Output type 用 pydantic 集成简化 `_dict_to_gql_context`；Input type 保持手写。删除 `_input_to_context`（直接用 `DrivingContext.model_validate` 替代）。

- [ ] **步骤 3：简化 mutation.py 中的转换函数**

```python
# app/api/resolvers/mutation.py

def _input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    """Convert Strawberry GraphQL input to Pydantic DrivingContext."""
    raw: dict[str, Any] = {}
    if input_obj.driver:
        raw["driver"] = {
            "emotion": input_obj.driver.emotion.value,
            "workload": input_obj.driver.workload.value,
            "fatigue_level": input_obj.driver.fatigue_level,
        }
    if input_obj.spatial:
        raw["spatial"] = _build_spatial_dict(input_obj.spatial)
    if input_obj.traffic:
        raw["traffic"] = {
            "congestion_level": input_obj.traffic.congestion_level.value,
            "incidents": input_obj.traffic.incidents,
            "estimated_delay_minutes": input_obj.traffic.estimated_delay_minutes,
        }
    raw["scenario"] = input_obj.scenario.value
    return DrivingContext.model_validate(raw)
```

删除 `_dict_to_gql_context`（不再需要 —— `DrivingContextGQL` 由 pydantic_type 生成，可直接构造）。`_to_gql_preset` 改为：

```python
def _to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=DrivingContextGQL.from_pydantic(ctx),
        created_at=p.get("created_at", ""),
    )
```

⚠️ `from_pydantic` 方法是 strawberry pydantic 集成生成的便捷构造器。实际方法名请确认（可能是 `from_instance` 或 `from_pydantic`）。

- [ ] **步骤 4：运行 lint + 类型检查**

运行：`uv run ruff check --fix && uv run ruff format && uv run ty check`
预期：All checks passed

- [ ] **步骤 5：运行 graphql 测试**

运行：`uv run pytest tests/test_graphql.py -v`
预期：PASS（跳过需 embedding 的）

- [ ] **步骤 6：Commit**

```bash
git add app/api/graphql_schema.py app/api/resolvers/mutation.py
git commit -m "refactor(api): simplify GQL-Pydantic mapping with strawberry.experimental.pydantic"
```


## 验证

### 完整 lint + 类型检查

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

### 完整测试

```bash
uv run pytest tests/ -v --ignore=tests/test_integration
```

预期：所有非外部依赖测试 PASS。
