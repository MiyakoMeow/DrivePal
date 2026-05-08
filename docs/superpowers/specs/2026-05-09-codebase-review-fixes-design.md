# 代码库修复规格说明

修复范围：代码评审中识别的 20 项问题（4 严重 + 5 中度 + 8 轻微 + 3 架构），按文件分组逐文件修复。

---

## 执行顺序

按文件分 7 批，每批改完跑测试。执行顺序与文件独一性——同一文件只在一批中改动，不跨批。

```
1. 存储层 (toml_store.py, init_data.py)
2. 模型层 (chat.py, settings.py)
3. 规则+Workflow (rules.py, workflow.py)
4. API resolvers (mutation.py, query.py, _helpers.py NEW)
5. API main (main.py)
6. 反馈修复: store.py 实现 update_feedback
```

批 4 包含 `mutation.py` 的 event_id 补传 + 异常类移入 _helpers + 抽取共享函数 + query.py 改导入 + `_strawberry_to_plain` 末路改 `raise TypeError`。批 6 独立处理 `store.py`。同一文件不跨批。

## 1. 存储层

### 1.1 `app/storage/toml_store.py` — Issue 7: 多余 `asyncio.to_thread`

```python
# 改前
if not await asyncio.to_thread(self.filepath.exists):
# 改后
if not self.filepath.exists():
```

`Path.exists()` 是轻量 stat 调用，无需过线程。

### 1.2 `app/storage/init_data.py` — Issue 16: dead data

简化 `strategies.toml` 默认值，去掉永不使用的字段（`reminder_weights`、`ignored_patterns`、`modified_keywords`、`cooldown_periods`）。

```python
"strategies.toml": {
    "preferred_time_offset": 15,
    "preferred_method": "visual",
},
```

## 2. 模型层

### 2.1 `app/models/chat.py` — Issue 2: semaphore concurrency 覆盖

`_acquire_slot` 以 `base_url or "default"` 为 key 传入 `_get_provider_semaphore`（即同 base_url 的 provider 共享 semaphore）。若已有 semaphore 且 concurrency 不同，记录 warning 并跳过（保留已有值）。

```python
_semaphore_cache: dict[str, tuple[asyncio.Semaphore, int]] = {}

async def _get_provider_semaphore(provider_name: str, concurrency: int) -> asyncio.Semaphore:
    async with _get_lock():
        if provider_name not in _semaphore_cache:
            _semaphore_cache[provider_name] = (asyncio.Semaphore(concurrency), concurrency)
        else:
            _, existing = _semaphore_cache[provider_name]
            if existing != concurrency:
                logger.warning(
                    "Semaphore for %r exists with concurrency=%d, ignoring concurrency=%d",
                    provider_name, existing, concurrency,
                )
        return _semaphore_cache[provider_name][0]
```

### 2.2 `app/models/chat.py` — Issue 3: `generate_stream` 吞 `json_mode`

从 `**kwargs` 弹出 `json_mode` 并传给 API 调用。

```python
async def generate_stream(self, ..., **kwargs: object) -> AsyncIterator[str]:
    json_mode = kwargs.pop("json_mode", False)
    ...
    create_kwargs: dict = {"model": ..., "messages": ..., "temperature": ...}
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}
    stream = await client.chat.completions.create(..., **create_kwargs, stream=True)
```

### 2.3 `app/models/chat.py` — Issue 12: `batch_generate` 硬编码 semaphore

加参数 `max_concurrency: int = 8`。

```python
async def batch_generate(self, prompts: list[str], system_prompt: str | None = None, max_concurrency: int = 8) -> list[str]:
    sem = asyncio.Semaphore(max_concurrency)
    ...
```

### 2.4 `app/models/settings.py` — Issue 8: `@cache` 永不失效

加 `clear_cache()` 类方法。

```python
@classmethod
def clear_cache(cls) -> None:
    cls.load.cache_clear()
```

## 3. 规则引擎

### 3.1 `app/agents/rules.py` — Issue 13: `_get_fatigue_threshold` 反复读 `os.environ`

加模块级缓存变量，进程生命期内只读一次环境变量。阈值变更需重启进程，与服务配置热加载策略一致（settings.py 亦为 @cache）。

```python
_fatigue_cache: float | None = None

def _get_fatigue_threshold() -> float:
    global _fatigue_cache
    if _fatigue_cache is not None:
        return _fatigue_cache
    raw = os.environ.get("FATIGUE_THRESHOLD", "0.7")
    ...  # validation 不变
    _fatigue_cache = value
    return value
```

## 4. Workflow

### 4.1 `app/agents/workflow.py` — Issue 4: `_search_memories` dict shape 不一致

统一两路径输出为 `MemoryEvent.model_dump()` 格式。搜索路径从 `SearchResult` 构造 `MemoryEvent` 再 dump。

```python
# 主路径（搜索命中）
events = await self.memory_module.search(user_input, mode=self._memory_mode)
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

# 回退路径（get_history）不变，仍为 MemoryEvent.model_dump()
```

### 4.2 `app/agents/workflow.py` — Issue 5: `raw` 泄漏

三处 `model_dump()` 改为 `model_dump(exclude={"raw"})`。

```python
# _context_node
context = {**parsed.model_dump(exclude={"raw"}), "current_datetime": ..., "related_events": ...}

# _task_node
task = (await self._call_llm_json(prompt)).model_dump(exclude={"raw"})

# _strategy_node
decision = (await self._call_llm_json(prompt)).model_dump(exclude={"raw"})
```

### 4.3 `app/agents/workflow.py` — Issue 10+11: `ReminderContent` + `_extract_content`

`ReminderContent` 类转为模块级函数 `_extract_reminder_content(decision) -> str`。删除 `_extract_content` 静态方法。

```python
def _extract_reminder_content(decision: dict) -> str:
    for key in ("reminder_content", "remind_content", "content"):
        val = decision.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            return val.get("text") or val.get("content") or "无提醒内容"
    return "无提醒内容"
```

### 4.4 `app/agents/workflow.py` — Issue 17: strategies 全量入 prompt

过滤空集合字段以减少 token 消耗。

```python
strategies = await self._strategies_store.read()
# 保留有实际内容的字段
relevant = {}
for k, v in strategies.items():
    if isinstance(v, (list, dict)) and not v:
        continue  # 空集合跳过
    relevant[k] = v
```

### 4.5 `app/agents/workflow.py` — Issue 18: `_strategies_store` 不可注入

`__init__` 加可选参数 `strategies_store: TOMLStore | None = None`。

```python
def __init__(self, ..., strategies_store: TOMLStore | None = None) -> None:
    ...
    self._strategies_store = strategies_store or TOMLStore(data_dir, Path("strategies.toml"), dict)
```

### 4.6 `app/agents/workflow.py` — Issue 19: 节点无错误隔离

`run_with_stages` 节点循环包 try/except，异常时记录日志、设置错误状态、中止流水线。

```python
for node_fn in self._nodes:
    try:
        updates = await node_fn(state)
        state.update(updates)
    except ChatModelUnavailableError:
        raise
    except Exception as e:
        logger.error("Workflow node %s failed: %s", node_fn.__name__, e)
        state["result"] = f"处理失败：{node_fn.__name__} 出错"
        stages.execution = {"error": str(e), "node": node_fn.__name__}
        break
```

## 5. API resolvers

### 5.1 `app/api/resolvers/_helpers.py` — NEW

从 `mutation.py` 抽取共享工具：

- `_preset_store() -> TOMLStore`
- `_to_gql_preset(p: dict) -> ScenarioPresetGQL`
- `_dict_to_gql_context(d: dict) -> DrivingContextGQL`（原 mutation.py 同名函数）
- `_strawberry_to_plain(obj: object) -> object`（原 mutation.py 同名函数，末路改 `raise TypeError`）
- `_input_to_context(input_obj: DrivingContextInput) -> DrivingContext`（原 mutation.py 同名函数）
- `_safe_memory_call(coro, context_msg) -> T`（原 mutation.py 同名函数）

GraphQL 异常类（`InternalServerError`、`GraphQLInvalidActionError`、`GraphQLEventNotFoundError`）一并移入 `_helpers.py`（因 `_safe_memory_call` 依赖 `InternalServerError`）。

### 5.2 `app/api/resolvers/query.py` — Issue 6

删除 `from app.api.resolvers.mutation import _preset_store, _to_gql_preset`，改为：

```python
from app.api.resolvers._helpers import _preset_store, _to_gql_preset
```

### 5.3 `app/api/resolvers/mutation.py` — Issue 6 + 9

- 导入从 `_helpers` 而非自引用
- `_strawberry_to_plain` 末路改为 `raise TypeError(f"Unsupported type: {type(obj).__name__}")`
- `submit_feedback` 中 `FeedbackData` 构造补 `event_id`
- 删除已移至 `_helpers` 的函数

## 6. API main

### 6.1 `app/api/main.py` — Issues 14 + 15

CORS 加注释说明限制：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # 原型；若加鉴权需显式 origin 列表
    ...
)
```

`Path.exists(WEBUI_DIR)` 改为 `WEBUI_DIR.exists()`。

## 7. 反馈修复

### 7.1 `mutation.py` — FeedbackData 构造缺 event_id（随批 4 API resolvers 修复）

`FeedbackData` schema 已有 `event_id` 字段（默认空串），但 `submit_feedback` 构造时未传入。补传：

```python
feedback = FeedbackData(
    event_id=feedback_input.event_id,
    action=safe_action,
    ...
)
```

注：此项修复合并到批 4（`mutation.py` 在批 4 中一并改动），避免同文件跨批。

### 7.2 `app/memory/memory_bank/store.py` — `update_feedback` 空实现

改为写入 `feedback.toml`：

```python
async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
    store = TOMLStore(self.data_dir, Path("feedback.toml"), list)
    entry = feedback.model_dump(exclude_none=True)
    entry["event_id"] = event_id
    entry["timestamp"] = datetime.now(UTC).isoformat()
    await store.append(entry)
```

注意：`TOMLStore` 构造轻量（仅设 path + 取共享锁），`feedback.toml` 已由 `init_data.py` 创建，无副作用。

## 测试验证

每批改完后：

```bash
uv run ruff check --fix
uv run ruff format
uv run ty check
uv run pytest tests/ -v  # 跳过 --test-llm 和 --test-embedding
```
