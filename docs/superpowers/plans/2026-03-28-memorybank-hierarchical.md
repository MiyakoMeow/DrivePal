# MemoryBank Hierarchical Memory Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `MemoryBankBackend` from flat event storage to a three-tier Interaction → Event → Summary hierarchy.

**Architecture:** Add `interactions.json` as a new storage file. `write_interaction()` writes raw conversation records and auto-aggregates into events. `search()` expands matched events with their child interactions. Non-memorybank modes are untouched.

**Tech Stack:** Python 3.13+, pytest, unittest.mock, JSONStore (existing)

---

### Task 1: Initialize interactions.json in storage

**Files:**
- Modify: `app/storage/init_data.py:17-32`

- [ ] **Step 1: Add interactions.json to init_storage**

In `init_storage()`, add `"interactions.json": []` to the `files` dict, right after `"events.json": []`:

```python
files = {
    "events.json": [],
    "interactions.json": [],
    "contexts.json": {},
    ...
}
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/test_storage.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add app/storage/init_data.py
git commit -m "feat(storage): add interactions.json to init storage"
```

---

### Task 2: Add interactions_store and write_interaction to MemoryBankBackend

**Files:**
- Modify: `app/memory/memory_bank.py:22-37` (constructor)
- Modify: `app/memory/memory_bank.py` (new methods)
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests for write_interaction**

Add to `tests/test_memory_bank.py`:

```python
class TestWriteInteraction:
    def test_write_interaction_creates_record(self, backend):
        interaction_id = backend.write_interaction("提醒我开会", "好的")
        interactions = backend.interactions_store.read()
        assert len(interactions) == 1
        assert interactions[0]["id"] == interaction_id
        assert interactions[0]["query"] == "提醒我开会"
        assert interactions[0]["response"] == "好的"
        assert interactions[0]["memory_strength"] == 1
        assert interactions[0]["event_id"] is not None

    def test_write_interaction_creates_event(self, backend):
        backend.write_interaction("提醒我开会", "好的")
        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["interaction_ids"] == [backend.interactions_store.read()[0]["id"]]
        assert events[0]["content"] == "提醒我开会"
        assert "updated_at" in events[0]

    def test_write_interaction_with_event_type(self, backend):
        backend.write_interaction("提醒我开会", "好的", event_type="meeting")
        events = backend.events_store.read()
        assert events[0]["type"] == "meeting"

    def test_write_interaction_returns_id(self, backend):
        interaction_id = backend.write_interaction("测试", "回复")
        assert isinstance(interaction_id, str)
        assert len(interaction_id) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestWriteInteraction -v`
Expected: FAIL (AttributeError: no `interactions_store` / `write_interaction`)

- [ ] **Step 3: Implement write_interaction**

In `app/memory/memory_bank.py`:

1. Add `AGGREGATION_SIMILARITY_THRESHOLD = 0.8` constant (top of file, after existing constants)
2. In `__init__`, add: `self.interactions_store = JSONStore(data_dir, "interactions.json", list)`
3. Add method:

```python
def write_interaction(
    self, query: str, response: str, event_type: str = "reminder"
) -> str:
    interaction_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    today = date.today().isoformat()
    interaction = {
        "id": interaction_id,
        "event_id": "",
        "query": query,
        "response": response,
        "timestamp": datetime.now().isoformat(),
        "memory_strength": 1,
        "last_recall_date": today,
    }
    self.interactions_store.append(interaction)

    append_event_id = self._should_append_to_event(interaction)
    if append_event_id:
        interaction["event_id"] = append_event_id
        self._append_interaction_to_event(append_event_id, interaction_id)
        self._update_event_summary(append_event_id)
    else:
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now().isoformat()
        event = {
            "id": event_id,
            "content": query,
            "type": event_type,
            "interaction_ids": [interaction_id],
            "created_at": now_iso,
            "updated_at": now_iso,
            "memory_strength": 1,
            "last_recall_date": today,
            "date_group": today,
        }
        self.events_store.append(event)
        interaction["event_id"] = event_id

    self._persist_interaction(interaction)
    self._maybe_summarize(today)
    return interaction_id
```

4. Add helper `_persist_interaction`:
```python
def _persist_interaction(self, interaction: dict) -> None:
    all_interactions = self.interactions_store.read()
    for i, item in enumerate(all_interactions):
        if item["id"] == interaction["id"]:
            all_interactions[i] = interaction
            break
    self.interactions_store.write(all_interactions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestWriteInteraction -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): add write_interaction with event auto-creation"
```

---

### Task 3: Implement event aggregation logic

**Files:**
- Modify: `app/memory/memory_bank.py` (new methods)
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests for aggregation**

```python
class TestEventAggregation:
    def test_first_interaction_creates_new_event(self, backend):
        iid = backend.write_interaction("提醒我开会", "好的")
        interactions = backend.interactions_store.read()
        assert interactions[0]["event_id"] != ""
        events = backend.events_store.read()
        assert len(events) == 1
        assert iid in events[0]["interaction_ids"]

    def test_similar_interaction_appends_to_event(self, backend):
        backend.write_interaction("提醒我明天上午开会", "好的")
        backend.write_interaction("改成下午三点", "已更新")
        events = backend.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2

    def test_different_interaction_creates_new_event(self, backend):
        backend.write_interaction("提醒我明天开会", "好的")
        backend.write_interaction("今天天气怎么样", "晴天")
        events = backend.events_store.read()
        assert len(events) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestEventAggregation -v`
Expected: FAIL (methods not yet implemented correctly)

- [ ] **Step 3: Implement _should_append_to_event and _append_interaction_to_event**

```python
def _should_append_to_event(self, interaction: dict) -> Optional[str]:
    events = self.events_store.read()
    if not events:
        return None
    today = date.today().isoformat()
    recent = events[-1]
    if recent.get("date_group") != today:
        return None
    if not self.embedding_model:
        return self._keyword_overlap(recent.get("content", ""), interaction["query"])
    query_vec = self.embedding_model.encode(interaction["query"])
    event_vec = self.embedding_model.encode(recent.get("content", ""))
    similarity = self._cosine_similarity(query_vec, event_vec)
    if similarity >= AGGREGATION_SIMILARITY_THRESHOLD:
        return recent["id"]
    return None

def _keyword_overlap(self, content: str, query: str) -> Optional[str]:
    content_lower = content.lower()
    query_lower = query.lower()
    query_words = [w for w in query_lower if len(w) > 1]
    if not query_words:
        return None
    overlap = sum(1 for w in query_words if w in content_lower)
    if overlap / len(query_words) >= 0.5:
        return None  # This should return event_id — see fix below
    return None
```

Wait — the `_keyword_overlap` helper needs access to the recent event's id. Let me restructure: `_should_append_to_event` handles both paths and returns `event_id` or `None` directly.

**Revised implementation for `_should_append_to_event`:**

```python
def _should_append_to_event(self, interaction: dict) -> Optional[str]:
    events = self.events_store.read()
    if not events:
        return None
    today = date.today().isoformat()
    recent = events[-1]
    if recent.get("date_group") != today:
        return None
    if self.embedding_model:
        query_vec = self.embedding_model.encode(interaction["query"])
        event_vec = self.embedding_model.encode(recent.get("content", ""))
        similarity = self._cosine_similarity(query_vec, event_vec)
        if similarity >= AGGREGATION_SIMILARITY_THRESHOLD:
            return recent["id"]
        return None
    content_lower = recent.get("content", "").lower()
    query_lower = interaction["query"].lower()
    words = [w for w in query_lower if len(w) > 1]
    if not words:
        return None
    overlap = sum(1 for w in words if w in content_lower)
    if overlap / len(words) >= 0.5:
        return recent["id"]
    return None
```

And `_append_interaction_to_event`:

```python
def _append_interaction_to_event(self, event_id: str, interaction_id: str) -> None:
    all_events = self.events_store.read()
    for event in all_events:
        if event.get("id") == event_id:
            event.setdefault("interaction_ids", []).append(interaction_id)
            event["updated_at"] = datetime.now().isoformat()
            break
    self.events_store.write(all_events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestEventAggregation -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement event aggregation logic"
```

---

### Task 4: Implement _update_event_summary (LLM)

**Files:**
- Modify: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing test**

```python
class TestUpdateEventSummary:
    def test_update_summary_calls_llm(self, temp_data_dir, mock_chat_model):
        backend = MemoryBankBackend(temp_data_dir, chat_model=mock_chat_model)
        mock_chat_model.generate.return_value = "用户修改了会议时间"
        iid1 = backend.write_interaction("提醒我开会", "好的", event_type="meeting")
        iid2 = backend.write_interaction("改成下午三点", "已更新")
        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["content"] == "用户修改了会议时间"
        assert mock_chat_model.generate.called

    def test_no_llm_no_summary_update(self, backend):
        iid1 = backend.write_interaction("提醒我开会", "好的")
        iid2 = backend.write_interaction("改成下午", "已更新")
        events = backend.events_store.read()
        assert events[0]["content"] == "提醒我开会"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_bank.py::TestUpdateEventSummary -v`
Expected: FAIL

- [ ] **Step 3: Implement _update_event_summary**

```python
def _update_event_summary(self, event_id: str) -> None:
    if not self.chat_model:
        return
    interactions = self.interactions_store.read()
    child_interactions = [i for i in interactions if i.get("event_id") == event_id]
    if not child_interactions:
        return
    combined = "\n".join(
        f"用户: {i['query']}\n系统: {i['response']}" for i in child_interactions
    )
    prompt = f"请简洁总结以下交互记录（一句话）：\n{combined}"
    try:
        summary_text = self.chat_model.generate(prompt)
    except Exception:
        return
    all_events = self.events_store.read()
    for event in all_events:
        if event.get("id") == event_id:
            event["content"] = summary_text
            break
    self.events_store.write(all_events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestUpdateEventSummary -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement LLM-based event summary update"
```

---

### Task 5: Expand search results with interactions and strengthen interactions on hit

**Files:**
- Modify: `app/memory/memory_bank.py:51-66` (search method)
- Modify: `app/memory/memory_bank.py:121-140` (_strengthen_events)
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests**

```python
class TestSearchWithInteractions:
    def test_search_expands_interactions(self, backend):
        backend.write_interaction("提醒我开会", "好的")
        backend.write_interaction("改成下午", "已更新")
        results = backend.search("开会")
        assert len(results) > 0
        top = results[0]
        assert "interactions" in top
        assert len(top["interactions"]) >= 1

    def test_search_strengthen_interactions_on_hit(self, backend):
        backend.write_interaction("重要会议", "已记录")
        backend.search("会议")
        interactions = backend.interactions_store.read()
        assert interactions[0]["memory_strength"] == 2

    def test_legacy_event_no_interactions_key(self, backend):
        backend.write_with_memory({"content": "旧事件"})
        results = backend.search("旧事件")
        assert len(results) > 0
        assert results[0].get("interactions", []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestSearchWithInteractions -v`
Expected: FAIL

- [ ] **Step 3: Modify search to expand interactions**

At the end of `search()`, before returning, add expansion:

```python
def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
    if not query.strip():
        return []
    events = self.events_store.read()
    summaries = self.summaries_store.read()
    daily_summaries = summaries.get("daily_summaries", {})
    if not events and not daily_summaries:
        return []
    if self.embedding_model is None:
        event_results = self._search_by_keyword(query, events, top_k)
    else:
        event_results = self._search_by_embedding(query, events, top_k)
    summary_results = self._search_summaries(query, daily_summaries, top_k=1)
    all_results = event_results + summary_results
    all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    top_results = all_results[:top_k]
    return self._expand_event_interactions(top_results)
```

Add `_expand_event_interactions`:

```python
def _expand_event_interactions(self, results: list[dict]) -> list[dict]:
    interactions = self.interactions_store.read()
    interaction_by_event: dict[str, list[dict]] = {}
    for i in interactions:
        eid = i.get("event_id", "")
        if eid:
            interaction_by_event.setdefault(eid, []).append(i)
    for result in results:
        eid = result.get("id", "")
        result["interactions"] = interaction_by_event.get(eid, [])
    return results
```

- [ ] **Step 4: Modify _strengthen_events to also strengthen interactions**

Add to `_strengthen_events`, after event strengthening succeeds:

```python
def _strengthen_events(self, matched_events: list[dict]) -> None:
    if not matched_events:
        return
    matched_ids = {e["id"] for e in matched_events if "id" in e}
    if not matched_ids:
        return
    all_events = self.events_store.read()
    today = date.today().isoformat()
    updated = False
    for event in all_events:
        if event.get("id") in matched_ids:
            event["memory_strength"] = event.get("memory_strength", 1) + 1
            event["last_recall_date"] = today
            updated = True
    if updated:
        self.events_store.write(all_events)
    for event in matched_events:
        if "id" in event:
            event["memory_strength"] = event.get("memory_strength", 1) + 1
            event["last_recall_date"] = today
    self._strengthen_interactions(matched_ids)
```

Add `_strengthen_interactions`:

```python
def _strengthen_interactions(self, event_ids: set[str]) -> None:
    if not event_ids:
        return
    all_interactions = self.interactions_store.read()
    today = date.today().isoformat()
    updated = False
    for interaction in all_interactions:
        if interaction.get("event_id") in event_ids:
            interaction["memory_strength"] = interaction.get("memory_strength", 1) + 1
            interaction["last_recall_date"] = today
            updated = True
    if updated:
        self.interactions_store.write(all_interactions)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestSearchWithInteractions -v`
Expected: All PASS

- [ ] **Step 6: Run full existing test suite to check no regressions**

Run: `pytest tests/test_memory_bank.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): expand search results with interactions, strengthen on hit"
```

---

### Task 6: Add write_interaction delegate to MemoryModule

**Files:**
- Modify: `app/memory/memory.py:113-124`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_memory.py`:

```python
def test_write_interaction_delegates(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    interaction_id = memory.write_interaction("测试查询", "测试回复")
    assert isinstance(interaction_id, str)
    results = memory.search("测试", mode="memorybank")
    assert len(results) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory.py::test_write_interaction_delegates -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Add write_interaction to MemoryModule**

```python
def write_interaction(self, query: str, response: str) -> str:
    backend = self._get_memorybank_backend()
    return backend.write_interaction(query, response)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py::test_write_interaction_delegates -v`
Expected: PASS

- [ ] **Step 5: Run full memory tests**

Run: `pytest tests/test_memory.py tests/test_memory_bank.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/memory/memory.py tests/test_memory.py
git commit -m "feat(memory): add write_interaction delegate to MemoryModule"
```

---

### Task 7: Update AgentWorkflow execution node

**Files:**
- Modify: `app/agents/workflow.py:180-199`

- [ ] **Step 1: Update _execution_node to use write_interaction**

Replace the memorybank branch in `_execution_node`:

```python
def _execution_node(self, state: AgentState) -> dict:
    decision = state.get("decision", {})
    messages = state.get("messages", [])
    user_input = str(messages[0].content) if messages else ""

    content = decision.get("content", "无提醒内容")
    if self.memory_mode == "memorybank":
        event_id = self.memory.write_interaction(user_input, content)
    else:
        event_data = {"content": content, "type": "reminder", "decision": decision}
        event_id = self.memory.write(event_data)
    if not event_id:
        logger.warning("Memory write returned empty event_id, using fallback")
        event_id = f"unknown_{hash(str(decision))}"

    result = f"提醒已发送: {content}"
    return {
        "result": result,
        "event_id": event_id,
        "messages": state["messages"] + [HumanMessage(content=result)],
    }
```

- [ ] **Step 2: Run existing workflow tests**

Run: `pytest tests/test_workflow.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat(workflow): use write_interaction for memorybank mode"
```

---

### Task 8: Run full test suite and lint

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run linter**

Run: `ruff check app/ tests/`
Expected: No errors

- [ ] **Step 3: Fix any lint issues if found**

Run: `ruff check --fix app/ tests/`

- [ ] **Step 4: Final commit if any fixes**

```bash
git add -A
git commit -m "chore: lint fixes"
```
