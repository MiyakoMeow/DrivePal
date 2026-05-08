# 代码库修复 实现计划

> **面向子 Agent 工作者：** 必需子技能：使用 superpowers:subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 修复代码评审识别的 19 项问题（4 严重 + 5 中度 + 7 轻微 + 3 架构；Issue 20 属架构观察，合并后自然缓解）

**方案：** 按文件分组，7 批次逐文件修复。每批改完跑 ruff check/format → ty check → pytest。

**技术栈：** Python 3.14, FastAPI, Strawberry GraphQL, Pydantic, openai SDK, aiofiles, tomli_w

---

### 任务 0：验证基线测试

**文件：** （无修改）

- [ ] **步骤 0.1：运行基线测试确认当前状态**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
uv run pytest tests/ -v -x --timeout=60 2>&1 | tail -40
```

预期：ruff/ty 无报错，pytest 全部通过（或跳过 LLM/embedding 测试）。

---

### 任务 1：存储层修复

**文件：**
- 修改：`app/storage/toml_store.py:107`
- 修改：`app/storage/init_data.py:35-41`

#### Issue 7：去除无用 `asyncio.to_thread`

- [ ] **步骤 1.1：替换 `asyncio.to_thread` 为直接调用**

`app/storage/toml_store.py` L107：

```python
# 改前
if not await asyncio.to_thread(self.filepath.exists):
# 改后
if not self.filepath.exists():
```

#### Issue 16：简化 strategies.toml 默认值

- [ ] **步骤 1.2：精简 strategies.toml 默认数据**

`app/storage/init_data.py` L35-41：

```python
# 改前
"strategies.toml": {
    "preferred_time_offset": 15,
    "preferred_method": "visual",
    "reminder_weights": {},
    "ignored_patterns": [],
    "modified_keywords": [],
    "cooldown_periods": {},
},
# 改后
"strategies.toml": {
    "preferred_time_offset": 15,
    "preferred_method": "visual",
},
```

- [ ] **步骤 1.3：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -30
```

- [ ] **步骤 1.4：Commit**

```bash
git add app/storage/toml_store.py app/storage/init_data.py
git commit -m "fix: remove asyncio.to_thread, simplify strategies.toml defaults"
```

---

### 任务 2：模型层修复 — chat.py

**文件：**
- 修改：`app/models/chat.py`

#### Issue 2：semaphore concurrency 缓存覆盖

- [ ] **步骤 2.1：改写 `_get_provider_semaphore` 缓存为 tuple 结构**

`app/models/chat.py`：

改 `_semaphore_cache` 类型及 `_get_provider_semaphore`：

```python
_semaphore_cache: dict[str, tuple[asyncio.Semaphore, int]] = {}

async def _get_provider_semaphore(
    provider_name: str, concurrency: int
) -> asyncio.Semaphore:
    async with _get_lock():
        if provider_name not in _semaphore_cache:
            _semaphore_cache[provider_name] = (
                asyncio.Semaphore(concurrency),
                concurrency,
            )
        else:
            _, existing_conc = _semaphore_cache[provider_name]
            if existing_conc != concurrency:
                logger.warning(
                    "Semaphore %r exists with concurrency=%d, ignoring %d",
                    provider_name,
                    existing_conc,
                    concurrency,
                )
        return _semaphore_cache[provider_name][0]
```

`clear_semaphore_cache()` 无需改（`_semaphore_cache.clear()` 清空 dict 即可）。

#### Issue 3：generate_stream 吞 `json_mode`

- [ ] **步骤 2.2：从 `**kwargs` 提取 `json_mode` 并传给 API**

`app/models/chat.py` L160-191：

```python
async def generate_stream(
    self,
    prompt: str = "",
    system_prompt: str | None = None,
    messages: list[ChatCompletionMessageParam] | None = None,
    **_kwargs: object,
) -> AsyncIterator[str]:
    if messages is None:
        messages = self._build_messages(prompt, system_prompt)
    json_mode = _kwargs.pop("json_mode", False) if _kwargs else False

    errors = []
    for provider in self.providers:
        sem = await self._acquire_slot(provider)
        try:
            async with sem, self._create_client(provider) as client:
                create_kwargs: dict = {
                    "model": provider.provider.model,
                    "messages": messages,
                    "temperature": self._get_temperature(provider),
                }
                if json_mode:
                    create_kwargs["response_format"] = {"type": "json_object"}
                stream = await client.chat.completions.create(
                    **create_kwargs, stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
                return
        except (openai.APIError, OSError, ValueError, TypeError, RuntimeError) as e:
            errors.append(f"{provider.provider.model}: {e}")
            continue
    raise AllProviderFailedError("; ".join(errors))
```

#### Issue 12：batch_generate 硬编码 semaphore

- [ ] **步骤 2.3：`batch_generate` 加 `max_concurrency` 参数**

```python
async def batch_generate(
    self,
    prompts: list[str],
    system_prompt: str | None = None,
    max_concurrency: int = 8,
) -> list[str]:
    if not prompts:
        return []
    sem = asyncio.Semaphore(max_concurrency)
    ...
```

- [ ] **步骤 2.4：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -30
```

- [ ] **步骤 2.5：Commit**

```bash
git add app/models/chat.py
git commit -m "fix: semaphore concurrency cache, stream json_mode, batch semaphore param"
```

---

### 任务 3：模型层修复 — settings.py

**文件：**
- 修改：`app/models/settings.py`

#### Issue 8：`@cache` 永不失效

- [ ] **步骤 3.1：加 `clear_cache()` 类方法**

`app/models/settings.py`，在 `load()` 方法后（仍在 `LLMSettings` 类内）：

```python
@classmethod
def clear_cache(cls) -> None:
    cls.load.cache_clear()
```

- [ ] **步骤 3.2：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x -k "not (llm or embedding or integration)" --timeout=60 2>&1 | tail -20
```

- [ ] **步骤 3.3：Commit**

```bash
git add app/models/settings.py
git commit -m "feat: add LLMSettings.clear_cache() for config reload"
```

---

### 任务 4：规则引擎修复

**文件：**
- 修改：`app/agents/rules.py`

#### Issue 13：`_get_fatigue_threshold` 反复读环境变量

- [ ] **步骤 4.1：加模块级缓存变量**

`app/agents/rules.py`，在 `_get_fatigue_threshold` 前加全局变量，函数内加缓存逻辑：

```python
_fatigue_threshold_cache: float | None = None

def _get_fatigue_threshold() -> float:
    global _fatigue_threshold_cache
    if _fatigue_threshold_cache is not None:
        return _fatigue_threshold_cache
    raw = os.environ.get("FATIGUE_THRESHOLD", "0.7")
    try:
        value = float(raw)
    except ValueError:
        ...
        _fatigue_threshold_cache = 0.7
        return 0.7
    if not math.isfinite(value):
        ...
        _fatigue_threshold_cache = 0.7
        return 0.7
    if not 0.0 <= value <= 1.0:
        ...
        _fatigue_threshold_cache = 0.7
        return 0.7
    _fatigue_threshold_cache = value
    return value
```

注意：其余验证逻辑（logging、边界检查）与原函数完全一致，仅增加全局缓存。

- [ ] **步骤 4.2：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/test_rules.py -v 2>&1 | tail -30
```

- [ ] **步骤 4.3：Commit**

```bash
git add app/agents/rules.py
git commit -m "fix: cache fatigue threshold to avoid repeated os.environ reads"
```

---

### 任务 5：Workflow 修复

**文件：**
- 修改：`app/agents/workflow.py`

#### Issue 4：_search_memories dict shape 不一致

- [ ] **步骤 5.1：统一 `_search_memories` 两路径输出为 MemoryEvent.model_dump() 格式**

```python
async def _search_memories(
    self, user_input: str,
) -> list[dict]:
    if not user_input:
        try:
            history = await self.memory_module.get_history(mode=self._memory_mode)
            return [e.model_dump() for e in history]
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Memory get_history failed for empty input: %s", e)
            return []

    try:
        events = await self.memory_module.search(
            user_input, mode=self._memory_mode,
        )
        if events:
            result = []
            for e in events:
                ed = e.event
                me = MemoryEvent(
                    content=ed.get("raw_content") or ed.get("text", ""),
                    type=ed.get("event_type", "reminder"),
                    memory_strength=int(ed.get("memory_strength", 1)),
                    created_at=ed.get("created_at", ""),
                    id=str(ed.get("id", "")),
                )
                d = me.model_dump()
                if e.interactions:
                    d["interactions"] = e.interactions
                result.append(d)
            return result
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
        logger.warning("Memory search failed, fallback to history: %s", e)

    try:
        history = await self.memory_module.get_history(mode=self._memory_mode)
        return [e.model_dump() for e in history]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
        logger.warning("Memory get_history also failed: %s", e)
        return []
```

需要导入 `MemoryEvent`：在文件顶部导入 `from app.memory.schemas import MemoryEvent`。

#### Issue 10 + 11：ReminderContent 类 + _extract_content

- [ ] **步骤 5.2：将 ReminderContent 类替换为模块级函数，删除 _extract_content**

删除 `ReminderContent` 整个类定义（L54-69）。加模块级函数：

```python
def _extract_reminder_content(decision: dict) -> str:
    """从 decision dict 中提取提醒内容，多处 key 兜底。"""
    for key in ("reminder_content", "remind_content", "content"):
        val = decision.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            return val.get("text") or val.get("content") or "无提醒内容"
    return "无提醒内容"
```

删除 `_extract_content` 静态方法（L228-231）。`_execution_node` 中 `content = self._extract_content(decision)` 改为 `content = _extract_reminder_content(decision)`。

#### Issue 5：raw 泄漏到各 stage

- [ ] **步骤 5.3：三处 `model_dump()` 加 `exclude={"raw"}`**

`_context_node` L166：
```python
context = {
    **parsed.model_dump(exclude={"raw"}),
    "current_datetime": current_datetime,
    "related_events": relevant_memories,
}
```

`_task_node` L190：
```python
task = (await self._call_llm_json(prompt)).model_dump(exclude={"raw"})
```

`_strategy_node` L220：
```python
decision = (await self._call_llm_json(prompt)).model_dump(exclude={"raw"})
```

#### Issue 17：strategies 全量灌入 prompt

- [ ] **步骤 5.4：过滤空集合字段**

`_strategy_node`，在 `json.dumps(strategies)` 前加过滤：

```python
strategies = await self._strategies_store.read()
# 跳过空集合字段以减少 token 消耗
relevant_strategies = {
    k: v for k, v in strategies.items()
    if not (isinstance(v, (list, dict)) and not v)
}
```

prompt 模板中的 `{json.dumps(strategies, ...)}` 改为 `{json.dumps(relevant_strategies, ...)}`。

#### Issue 18：_strategies_store 不可注入

- [ ] **步骤 5.5：`__init__` 加可选参数**

```python
def __init__(
    self,
    data_dir: Path = Path("data"),
    memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
    memory_module: MemoryModule | None = None,
    strategies_store: TOMLStore | None = None,
) -> None:
    ...
    self._strategies_store = strategies_store or TOMLStore(
        data_dir, Path("strategies.toml"), dict,
    )
    # 删除旧的 self._strategies_store = TOMLStore(...)
```

#### Issue 19：节点无错误隔离

- [ ] **步骤 5.6：`run_with_stages` 节点循环加 error handling**

```python
for node_fn in self._nodes:
    try:
        updates = await node_fn(state)
        state.update(updates)
    except ChatModelUnavailableError:
        raise
    except Exception as e:
        logger.error("Workflow node %s failed: %s", node_fn.__name__, e)
        state["result"] = f"处理失败：{node_fn.__name__} 阶段出错"
        if stages is not None:
            stages.execution = {"error": str(e), "node": node_fn.__name__}
        break
```

- [ ] **步骤 5.7：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -30
```

- [ ] **步骤 5.8：Commit**

```bash
git add app/agents/workflow.py
git commit -m "fix: workflow search shape, raw leak, reminder func, strategies filter, DI, error isolation"
```

---

### 任务 6：API Resolvers 重构

**文件：**
- 创建：`app/api/resolvers/_helpers.py`
- 修改：`app/api/resolvers/mutation.py`
- 修改：`app/api/resolvers/query.py`

#### Issue 6 + 9：抽取共享模块 + 加类型安全 + 补 event_id

- [ ] **步骤 6.1：创建 `_helpers.py`**

从 `mutation.py` 移动以下函数和异常类：

函数（代码完全一致，仅 `_strawberry_to_plain` 末路改 `raise TypeError`）：
- `_preset_store() -> TOMLStore`
- `_to_gql_preset(p: dict) -> ScenarioPresetGQL`
- `_dict_to_gql_context(d: dict) -> DrivingContextGQL`
- `_strawberry_to_plain(obj: object) -> object`（末路从 `return obj` 改为 `raise TypeError(f"Unsupported type: {type(obj).__name__}")`）
- `_input_to_context(input_obj: DrivingContextInput) -> DrivingContext`
- `_safe_memory_call[T](coro: Awaitable[T], context_msg: str) -> T`

异常类（全部移入 _helpers）：
- `InternalServerError(GraphQLError)`
- `GraphQLInvalidActionError(GraphQLError)`
- `GraphQLEventNotFoundError(GraphQLError)`

`_helpers.py` 所需导入：
```python
import dataclasses
import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import strawberry
from graphql.error import GraphQLError

if TYPE_CHECKING:
    from collections.abc import Awaitable

from app.api.graphql_schema import (
    DriverStateGQL, DrivingContextGQL, DrivingContextInput,
    GeoLocationGQL, ScenarioPresetGQL, SpatioTemporalContextGQL, TrafficConditionGQL,
)
from app.config import DATA_DIR
from app.schemas.context import DrivingContext

logger = logging.getLogger(__name__)
```

- [ ] **步骤 6.2：更新 `mutation.py` — 从 _helpers 导入 + 补 event_id**

删除已移至 `_helpers.py` 的函数。改为：

```python
from app.api.resolvers._helpers import (
    _input_to_context,
    _preset_store,
    _safe_memory_call,
    _strawberry_to_plain,
    _to_gql_preset,
    InternalServerError,
    GraphQLInvalidActionError,
    GraphQLEventNotFoundError,
)
```

保留 `submit_feedback`、`process_query`、`save_scenario_preset`、`delete_scenario_preset`。

在 `submit_feedback` 中，`FeedbackData` 构造补 `event_id`：

```python
feedback = FeedbackData(
    event_id=feedback_input.event_id,  # ← 补传
    action=safe_action,
    type=actual_type,
    modified_content=feedback_input.modified_content,
)
```

- [ ] **步骤 6.3：更新 `query.py` — 从 _helpers 导入**

```python
# 删除：from app.api.resolvers.mutation import _preset_store, _to_gql_preset
# 改为：
from app.api.resolvers._helpers import _preset_store, _to_gql_preset
```

- [ ] **步骤 6.4：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -30
```

- [ ] **步骤 6.5：Commit**

```bash
git add app/api/resolvers/
git commit -m "refactor: extract shared helpers from resolvers, fix _strawberry_to_plain type safety"
```

---

### 任务 7：API main 修复

**文件：**
- 修改：`app/api/main.py`

#### Issue 14：CORS 注释 + Issue 15：Path.exists 调用

- [ ] **步骤 7.1：CORS 加注释，修复 Path.exists 调用**

`app/api/main.py` L40：

```python
# 改前
if not Path.exists(WEBUI_DIR):
# 改后
if not WEBUI_DIR.exists():
```

L46-51：

```python
# 改前
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 改后（加注释说明限制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # 原型阶段允许；若加鉴权需改用显式 origin 列表
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **步骤 7.2：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -20
```

- [ ] **步骤 7.3：Commit**

```bash
git add app/api/main.py
git commit -m "fix: WEBUI_DIR.exists() call, add CORS comment"
```

---

### 任务 8：反馈修复

**文件：**
- 修改：`app/api/resolvers/mutation.py`
- 修改：`app/memory/memory_bank/store.py`

#### Issue 1：feedback 空洞（store.py 实现；mutation.py 的 event_id 补传已在 Task 6 完成）

- [ ] **步骤 8.1：memory_bank/store.py — 实现 update_feedback**

在 `store.py` 顶部添加导入：

```python
from datetime import UTC, datetime
from pathlib import Path
from app.storage.toml_store import TOMLStore
```

实现方法：

```python
async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
    store = TOMLStore(self.data_dir, Path("feedback.toml"), list)
    entry = feedback.model_dump(exclude_none=True)
    entry["event_id"] = event_id
    entry["timestamp"] = datetime.now(UTC).isoformat()
    await store.append(entry)
```

- [ ] **步骤 8.2：运行 lint + type check + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v -x --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -30
```

- [ ] **步骤 8.3：Commit**

```bash
git add app/memory/memory_bank/store.py
git commit -m "fix: implement update_feedback in MemoryBankStore"
```

---

### 任务 9：最终验证

- [ ] **步骤 9.1：全量测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v --timeout=60 -k "not (llm or embedding or integration)" 2>&1 | tail -50
```

- [ ] **步骤 9.2：如有失败，修之。**
