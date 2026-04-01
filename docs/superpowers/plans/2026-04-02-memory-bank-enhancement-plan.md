# 记忆库增强：软遗忘 + 人格摘要 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现软遗忘机制和人格摘要分析功能，对标 MemoryBank-SiliconFriend

**Architecture:** 在 `MemoryBankEngine` 中新增软遗忘、每日人格摘要、整体人格画像、及人格摘要搜索功能。人格摘要独立存储于 `memorybank_personality.json`。

**Tech Stack:** Python asyncio, JSONStore, ChatModel

---

## 任务概览

| 任务 | 描述 |
|------|------|
| Task 1 | 软遗忘机制实现 |
| Task 2 | 人格摘要存储初始化 |
| Task 3 | 每日人格摘要生成 |
| Task 4 | 整体人格汇总 |
| Task 5 | 人格摘要搜索 |
| Task 6 | 数据流整合（write_interaction + search） |
| Task 7 | 测试 |

---

## Task 1: 软遗忘机制实现

**Files:**
- Modify: `app/memory/components.py:16-30`

- [ ] **Step 1: 添加软遗忘常量**

在 `forgetting_curve` 函数后添加：

```python
SOFT_FORGET_THRESHOLD = 0.15
SOFT_FORGET_STRENGTH = 0.1
```

- [ ] **Step 2: 在 `MemoryBankEngine` 中添加 `_soft_forget_events` 方法**

在 `_strengthen_events` 方法后添加：

```python
async def _soft_forget_events(self, all_events: list[dict], matched_ids: set[str]) -> None:
    """对 retention 过低的记忆执行软遗忘"""
    today = datetime.now(timezone.utc).date()
    updated = False
    for event in all_events:
        if event.get("id") in matched_ids:
            continue
        strength = event.get("memory_strength", 1)
        last_recall = event.get("last_recall_date", today.isoformat())
        try:
            last_date = date.fromisoformat(last_recall)
            days_elapsed = (today - last_date).days
        except (ValueError, TypeError):
            days_elapsed = 0
        retention = forgetting_curve(days_elapsed, strength)
        if retention < SOFT_FORGET_THRESHOLD:
            event["memory_strength"] = SOFT_FORGET_STRENGTH
            event["forgotten"] = True
            updated = True
    if updated:
        await self._storage.write_events(all_events)
```

- [ ] **Step 3: 修改 `_strengthen_events` 末尾调用软遗忘**

在 `_strengthen_events` 方法末尾（约第292行），`await self._strengthen_interactions(matched_ids)` 之后添加：

```python
all_events = await self._storage.read_events()
await self._soft_forget_events(all_events, matched_ids)
```

- [ ] **Step 4: 运行类型检查和 lint**

```bash
uv run ruff check --fix app/memory/components.py
uv run ty check app/memory/components.py
```

- [ ] **Step 5: 提交**

```bash
git add app/memory/components.py
git commit -m "feat(memory): add soft forget mechanism"
```

---

## Task 2: 人格摘要存储初始化

**Files:**
- Modify: `app/memory/components.py:150-169`

- [ ] **Step 1: 在 `MemoryBankEngine.__init__` 中初始化 `_personality_store`**

在 `__init__` 方法中，`self._summaries_store` 初始化之后添加：

```python
self._personality_store = JSONStore(
    data_dir,
    Path("memorybank_personality.json"),
    lambda: {"daily_personality": {}, "overall_personality": ""},
)
```

- [ ] **Step 2: 添加人格摘要常量**

在文件顶部常量区添加：

```python
PERSONALITY_SUMMARY_THRESHOLD = 2
OVERALL_PERSONALITY_THRESHOLD = 3
```

- [ ] **Step 3: 运行类型检查和 lint**

```bash
uv run ruff check --fix app/memory/components.py
uv run ty check app/memory/components.py
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/components.py
git commit -m "feat(memory): add personality store initialization"
```

---

## Task 3: 每日人格摘要生成

**Files:**
- Modify: `app/memory/components.py` (在 `_maybe_summarize` 方法后添加)

- [ ] **Step 1: 添加 `_maybe_summarize_personality` 方法**

在 `_update_overall_summary` 方法之前添加：

```python
async def _maybe_summarize_personality(self, date_group: str) -> None:
    """每日对话达到阈值时，生成人格分析摘要"""
    if not self.chat_model:
        return
    events = await self._storage.read_events()
    group_events = [e for e in events if e.get("date_group") == date_group]
    count = len(group_events)
    if count < PERSONALITY_SUMMARY_THRESHOLD:
        return
    personality_data = await self._personality_store.read()
    daily_personality = personality_data.get("daily_personality", {})
    if date_group in daily_personality:
        return
    interactions = await self._interactions_store.read()
    group_interactions = [
        i for i in interactions if i.get("event_id") in {e.get("id") for e in group_events}
    ]
    if len(group_interactions) < PERSONALITY_SUMMARY_THRESHOLD:
        return
    combined = "\n".join(
        f"用户: {i['query']}\n系统: {i['response']}" for i in group_interactions
    )
    prompt = f"""Based on the following dialogue, please summarize user's personality traits and emotions, 
and devise response strategies based on your speculation. Dialogue content:
{combined}

User's personality traits, emotions, and response strategy are:
"""
    try:
        summary_text = await self.chat_model.generate(prompt)
    except Exception:
        return
    daily_personality[date_group] = {
        "content": summary_text,
        "memory_strength": 1,
        "last_recall_date": date_group,
    }
    personality_data["daily_personality"] = daily_personality
    await self._personality_store.write(personality_data)
    if len(daily_personality) >= OVERALL_PERSONALITY_THRESHOLD:
        await self._update_overall_personality(personality_data)
```

- [ ] **Step 2: 添加 `_update_overall_personality` 方法**

在 `_maybe_summarize_personality` 之后添加：

```python
async def _update_overall_personality(self, personality_data: dict) -> None:
    """汇总多条每日人格分析为整体人格档案"""
    if not self.chat_model:
        return
    daily_personality = personality_data.get("daily_personality", {})
    all_summaries = [
        f"[{date_group}] {data.get('content', '')}"
        for date_group, data in daily_personality.items()
        if isinstance(data, dict)
    ]
    combined = "\n".join(all_summaries)
    prompt = f"""The following are the user's exhibited personality traits and emotions throughout multiple dialogues, 
along with appropriate response strategies for the current situation:
{combined}

Please provide a highly concise and general summary of the user's personality and the most appropriate 
response strategy for the AI lover, summarized as:
"""
    try:
        overall = await self.chat_model.generate(prompt)
    except Exception:
        return
    personality_data["overall_personality"] = overall
    await self._personality_store.write(personality_data)
```

- [ ] **Step 3: 运行类型检查和 lint**

```bash
uv run ruff check --fix app/memory/components.py
uv run ty check app/memory/components.py
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/components.py
git commit -m "feat(memory): add personality summarization methods"
```

---

## Task 4: 人格摘要搜索

**Files:**
- Modify: `app/memory/components.py`

- [ ] **Step 1: 添加 `_search_personality` 方法**

在 `_strengthen_summaries` 方法后添加：

```python
async def _search_personality(self, query: str, top_k: int) -> list[SearchResult]:
    """搜索人格摘要，使用关键词匹配，retention 权重为 SUMMARY_WEIGHT * 0.8"""
    personality_data = await self._personality_store.read()
    daily_personality = personality_data.get("daily_personality", {})
    if not daily_personality:
        return []
    query_lower = query.lower()
    today = datetime.now(timezone.utc).date()
    results = []
    for date_group, data in daily_personality.items():
        if not isinstance(data, dict):
            continue
        content = data.get("content", "")
        if query_lower in content.lower():
            strength = data.get("memory_strength", 1)
            last_recall = data.get("last_recall_date", date_group)
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except (ValueError, TypeError):
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            score = retention * SUMMARY_WEIGHT * 0.8
            results.append(
                SearchResult(
                    event={
                        "content": content,
                        "date_group": date_group,
                        "memory_strength": strength,
                        "last_recall_date": last_recall,
                    },
                    score=score,
                    source="personality",
                )
            )
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_k]
```

- [ ] **Step 2: 运行类型检查和 lint**

```bash
uv run ruff check --fix app/memory/components.py
uv run ty check app/memory/components.py
```

- [ ] **Step 3: 提交**

```bash
git add app/memory/components.py
git commit -m "feat(memory): add personality search method"
```

---

## Task 5: 数据流整合

**Files:**
- Modify: `app/memory/components.py`

- [ ] **Step 1: 修改 `search()` 方法添加人格摘要搜索**

在 `search()` 方法中（约第199行），在 `summary_results = await self._search_summaries(...)` 之后添加人格摘要搜索：

```python
personality_results = await self._search_personality(query, top_k=1)
all_results = event_results + summary_results + personality_results
```

- [ ] **Step 2: 修改 `write_interaction()` 方法调用人格摘要**

在 `write_interaction()` 方法中（约第419行），在 `await self._maybe_summarize(today)` 之后添加：

```python
await self._maybe_summarize_personality(today)
```

- [ ] **Step 3: 运行类型检查和 lint**

```bash
uv run ruff check --fix app/memory/components.py
uv run ty check app/memory/components.py
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/components.py
git commit -m "feat(memory): integrate personality into search and write_interaction"
```

---

## Task 6: 测试

**Files:**
- Modify: `tests/test_components.py`

- [ ] **Step 1: 添加软遗忘测试**

在 `TestMemoryBankEngineWriteInteraction` 类之后添加：

```python
class TestSoftForget:
    """软遗忘机制测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        return MemoryBankEngine(tmp_path, storage)

    async def test_soft_forget_reduces_strength(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证 retention 过低时 memory_strength 降至 SOFT_FORGET_STRENGTH"""
        from datetime import date, timedelta
        from app.memory.components import SOFT_FORGET_STRENGTH

        await engine.write(MemoryEvent(content="旧事件"))
        events = await storage.read_events()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        events[0]["last_recall_date"] = old_date
        events[0]["memory_strength"] = 1
        await storage.write_events(events)

        matched_ids = set()
        all_events = await storage.read_events()
        await engine._soft_forget_events(all_events, matched_ids)

        updated_events = await storage.read_events()
        assert updated_events[0]["memory_strength"] == SOFT_FORGET_STRENGTH
        assert updated_events[0]["forgotten"] is True

    async def test_soft_forget_skips_recent_events(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证最近记忆不会被软遗忘"""
        await engine.write(MemoryEvent(content="新事件"))
        events = await storage.read_events()
        matched_ids = {events[0]["id"]}
        all_events = await storage.read_events()
        await engine._soft_forget_events(all_events, matched_ids)

        updated_events = await storage.read_events()
        assert updated_events[0]["memory_strength"] == 1
        assert updated_events[0].get("forgotten") is None


class TestPersonalitySummary:
    """人格摘要测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        return MemoryBankEngine(tmp_path, storage)

    async def test_maybe_summarize_personality_skips_without_chat_model(
        self, engine: MemoryBankEngine
    ) -> None:
        """验证无 chat_model 时跳过人格摘要"""
        today = datetime.now(timezone.utc).date().isoformat()
        await engine._maybe_summarize_personality(today)
        personality_data = await engine._personality_store.read()
        assert personality_data["daily_personality"] == {}
```

- [ ] **Step 2: 运行测试验证**

```bash
uv run pytest tests/test_components.py -v
```

- [ ] **Step 3: 运行完整检查**

```bash
uv run ruff check --fix
uv run ty check
uv run ruff format
```

- [ ] **Step 4: 提交**

```bash
git add tests/test_components.py
git commit -m "test(memory): add tests for soft forget and personality summary"
```

---

## Task 7: 集成测试

- [ ] **Step 1: 运行完整测试套件**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 2: 提交所有更改**

```bash
git add -A
git commit -m "feat: implement soft forget and personality summary"
```
