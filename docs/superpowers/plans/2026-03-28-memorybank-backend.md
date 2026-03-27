# MemoryBank Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `memorybank` as a fourth memory retrieval mode with Ebbinghaus forgetting curve, hierarchical summarization, and recall-based memory strengthening.

**Architecture:** New `MemoryBankBackend` class in `app/memory/memory_bank.py`. Integrated via new branch in `MemoryModule.search()`. Reuses existing BGE-small-zh-v1.5 embeddings + numpy cosine similarity. No FAISS dependency.

**Tech Stack:** Python 3.13+, LangChain, BGE-small-zh-v1.5, pytest

---

### Task 1: Forgetting Curve Core Logic

**Files:**
- Create: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests for forgetting curve and memory metadata**

```python
# tests/test_memory_bank.py
import pytest
from datetime import datetime, timedelta
from app.memory.memory_bank import forgetting_curve, MemoryBankBackend


class TestForgettingCurve:
    def test_high_strength_recent_recall(self):
        """High strength + recent recall = high retention"""
        retention = forgetting_curve(days_elapsed=0, strength=5)
        assert retention == pytest.approx(1.0, abs=0.01)

    def test_low_strength_old_recall(self):
        """Low strength + old recall = low retention"""
        retention = forgetting_curve(days_elapsed=30, strength=1)
        assert retention < 0.01

    def test_zero_days_always_one(self):
        """Same day recall always returns ~1.0"""
        retention = forgetting_curve(days_elapsed=0, strength=1)
        assert retention == pytest.approx(1.0, abs=0.001)

    def test_retention_decreases_with_time(self):
        """Longer time = lower retention"""
        r1 = forgetting_curve(days_elapsed=1, strength=1)
        r2 = forgetting_curve(days_elapsed=10, strength=1)
        assert r1 > r2

    def test_retention_increases_with_strength(self):
        """Higher strength = slower forgetting"""
        r1 = forgetting_curve(days_elapsed=5, strength=1)
        r2 = forgetting_curve(days_elapsed=5, strength=10)
        assert r2 > r1


class TestMemoryBankBackendInit:
    def test_init_creates_backend(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        assert backend.data_dir == str(tmp_path)

    def test_init_creates_summaries_file(self, tmp_path):
        MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        summaries_file = tmp_path / "memorybank_summaries.json"
        assert summaries_file.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'app.memory.memory_bank'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/memory/memory_bank.py
import json
import math
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from app.storage.json_store import JSONStore
from app.models.embedding import EmbeddingModel
from app.models.chat import ChatModel


DAILY_SUMMARY_THRESHOLD = 5
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankBackend:
    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ):
        self.data_dir = data_dir
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.summaries_store = JSONStore(
            data_dir, "memorybank_summaries.json", self._default_summaries
        )

    @staticmethod
    def _default_summaries() -> dict:
        return {"daily_summaries": {}, "overall_summary": ""}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): add forgetting curve and MemoryBankBackend init"
```

---

### Task 2: Memory Write with Metadata

**Files:**
- Modify: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory_bank.py (append to file)

class TestWriteWithMemory:
    def test_write_adds_memory_metadata(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        event_id = backend.write_with_memory({"content": "test event", "type": "meeting"})

        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["memory_strength"] == 1
        assert events[0]["last_recall_date"] == date.today().isoformat()
        assert events[0]["date_group"] == date.today().isoformat()
        assert "id" in events[0]
        assert event_id == events[0]["id"]

    def test_write_preserves_existing_fields(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        backend.write_with_memory({"content": "test", "type": "reminder", "custom": "value"})
        events = backend.events_store.read()
        assert events[0]["custom"] == "value"
        assert events[0]["created_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestWriteWithMemory -v`
Expected: FAIL - `AttributeError: 'MemoryBankBackend' object has no attribute 'write_with_memory'`

- [ ] **Step 3: Implement write_with_memory**

Add to `MemoryBankBackend` class in `app/memory/memory_bank.py`:

```python
    def write_with_memory(self, event: dict) -> str:
        today = date.today().isoformat()
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        event["memory_strength"] = event.get("memory_strength", 1)
        event["last_recall_date"] = today
        event["date_group"] = today
        self.events_store.append(event)
        self._maybe_summarize(today)
        return event_id
```

Also add `import uuid` to the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestWriteWithMemory -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement write_with_memory with metadata"
```

---

### Task 3: Search with Forgetting-Weighted Scoring

**Files:**
- Modify: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory_bank.py (append)

class TestSearchWithForgetting:
    def _make_backend(self, tmp_path):
        return MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )

    def test_search_no_embedding_model_returns_keyword(self, tmp_path):
        backend = self._make_backend(tmp_path)
        backend.write_with_memory({"content": "下午三点开会", "type": "meeting"})
        results = backend.search("开会")
        assert len(results) == 1
        assert "三点" in results[0]["content"]

    def test_search_empty_events(self, tmp_path):
        backend = self._make_backend(tmp_path)
        results = backend.search("anything")
        assert results == []

    def test_search_returns_top_k(self, tmp_path):
        backend = self._make_backend(tmp_path)
        for i in range(10):
            backend.write_with_memory({"content": f"event number {i}", "type": "general"})
        results = backend.search("event")
        assert len(results) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestSearchWithForgetting -v`
Expected: FAIL - `AttributeError: 'MemoryBankBackend' object has no attribute 'search'`

- [ ] **Step 3: Implement search**

Add to `MemoryBankBackend`:

```python
    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        events = self.events_store.read()
        if not events:
            return []
        if not query.strip():
            return []

        if self.embedding_model is None:
            return self._search_by_keyword(query, events, top_k)
        return self._search_by_embedding(query, events, top_k)

    def _search_by_keyword(self, query: str, events: list[dict], top_k: int) -> list[dict]:
        query_lower = query.lower()
        scored = []
        today = date.today()
        for event in events:
            content = event.get("content", "").lower()
            if query_lower not in content:
                continue
            last_recall = event.get("last_recall_date", event.get("created_at", "")[:10])
            days_elapsed = (today - date.fromisoformat(last_recall)).days
            strength = event.get("memory_strength", 1)
            retention = forgetting_curve(days_elapsed, strength)
            scored.append((event, retention))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    def _search_by_embedding(
        self, query: str, events: list[dict], top_k: int
    ) -> list[dict]:
        query_vec = self.embedding_model.encode(query)
        today = date.today()
        scored = []
        for event in events:
            content = event.get("content", "")
            event_vec = self.embedding_model.encode(content)
            similarity = self._cosine_similarity(query_vec, event_vec)
            last_recall = event.get("last_recall_date", event.get("created_at", "")[:10])
            days_elapsed = (today - date.fromisoformat(last_recall)).days
            strength = event.get("memory_strength", 1)
            retention = forgetting_curve(days_elapsed, strength)
            final_score = similarity * retention
            scored.append((event, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestSearchWithForgetting -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement search with forgetting-weighted scoring"
```

---

### Task 4: Recall-Based Memory Strengthening

**Files:**
- Modify: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory_bank.py (append)

class TestRecallStrengthening:
    def test_search_increases_memory_strength(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        backend.write_with_memory({"content": "下午开会", "type": "meeting"})
        backend.search("开会")
        events = backend.events_store.read()
        assert events[0]["memory_strength"] == 2
        assert events[0]["last_recall_date"] == date.today().isoformat()

    def test_search_updates_only_matched_events(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        backend.write_with_memory({"content": "下午开会", "type": "meeting"})
        backend.write_with_memory({"content": "去买菜", "type": "shopping"})
        backend.search("开会")
        events = backend.events_store.read()
        meeting_event = next(e for e in events if "开会" in e["content"])
        shopping_event = next(e for e in events if "买菜" in e["content"])
        assert meeting_event["memory_strength"] == 2
        assert shopping_event["memory_strength"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestRecallStrengthening -v`
Expected: FAIL - strength stays 1 after search

- [ ] **Step 3: Update search methods to strengthen recalled events**

Modify `_search_by_keyword` and `_search_by_embedding` to strengthen returned events. Refactor: extract the strengthen logic into a helper and call it after scoring.

```python
    def _strengthen_events(self, matched_events: list[dict]) -> None:
        today = date.today().isoformat()
        events = self.events_store.read()
        matched_ids = {e["id"] for e in matched_events}
        changed = False
        for event in events:
            if event["id"] in matched_ids:
                event["memory_strength"] += 1
                event["last_recall_date"] = today
                changed = True
        if changed:
            self.events_store.write(events)
```

Call `self._strengthen_events(returned)` at the end of both `_search_by_keyword` and `_search_by_embedding`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestRecallStrengthening -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement recall-based memory strengthening"
```

---

### Task 5: Hierarchical Summarization

**Files:**
- Modify: `app/memory/memory_bank.py`
- Test: `tests/test_memory_bank.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory_bank.py (append)

from unittest.mock import MagicMock


class TestHierarchicalSummarization:
    def test_summarize_trigger_threshold(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        today = date.today().isoformat()
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write_with_memory({"content": f"event {i}", "type": "general", "date_group": today})
        summaries = backend.summaries_store.read()
        assert today in summaries["daily_summaries"]

    def test_no_summary_below_threshold(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=None,
        )
        backend.write_with_memory({"content": "only one event", "type": "general"})
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0

    def test_overall_summary_trigger(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=MagicMock(),
        )
        backend.chat_model.generate.return_value = "Overall: user is busy"
        for d in range(OVERALL_SUMMARY_THRESHOLD):
            day = (date.today() - timedelta(days=d)).isoformat()
            for i in range(DAILY_SUMMARY_THRESHOLD):
                backend.write_with_memory(
                    {"content": f"event {d}-{i}", "type": "general", "date_group": day}
                )
        summaries = backend.summaries_store.read()
        assert summaries["overall_summary"] == "Overall: user is busy"

    def test_summaries_included_in_search(self, tmp_path):
        backend = MemoryBankBackend(
            data_dir=str(tmp_path),
            embedding_model=None,
            chat_model=MagicMock(),
        )
        backend.chat_model.generate.return_value = "Daily summary about meetings"
        today = date.today().isoformat()
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write_with_memory({"content": f"meeting {i}", "type": "meeting", "date_group": today})
        results = backend.search("meeting")
        has_summary = any(
            "daily_summary" in e.get("_source", "")
            for e in results
        )
        assert has_summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_bank.py::TestHierarchicalSummarization -v`
Expected: FAIL

- [ ] **Step 3: Implement summarization logic**

Add to `MemoryBankBackend`:

```python
    def _maybe_summarize(self, date_group: str) -> None:
        events = self.events_store.read()
        date_events = [e for e in events if e.get("date_group") == date_group]
        if len(date_events) < DAILY_SUMMARY_THRESHOLD:
            return

        summaries = self.summaries_store.read()
        if date_group in summaries.get("daily_summaries", {}):
            date_events_after = [
                e for e in date_events
                if e.get("created_at", "") > summaries["daily_summaries"][date_group].get("summarized_at", "")
            ]
            if len(date_events_after) < DAILY_SUMMARY_THRESHOLD:
                return

        if self.chat_model is None:
            return

        content = "\n".join(e.get("content", "") for e in date_events)
        prompt = f"请简洁总结以下事件（一句话）：\n{content}"
        try:
            summary_text = self.chat_model.generate(prompt)
        except Exception:
            return

        if "daily_summaries" not in summaries:
            summaries["daily_summaries"] = {}
        summaries["daily_summaries"][date_group] = {
            "content": summary_text,
            "memory_strength": 1,
            "last_recall_date": date_group,
            "summarized_at": datetime.now().isoformat(),
        }
        self.summaries_store.write(summaries)

        if len(summaries["daily_summaries"]) >= OVERALL_SUMMARY_THRESHOLD:
            self._update_overall_summary(summaries)

    def _update_overall_summary(self, summaries: dict) -> None:
        entries = list(summaries["daily_summaries"].items())
        content = "\n".join(f"{d}: {s['content']}" for d, s in entries)
        prompt = f"请高度概括以下每日摘要（一句话）：\n{content}"
        try:
            summaries["overall_summary"] = self.chat_model.generate(prompt)
            self.summaries_store.write(summaries)
        except Exception:
            pass
```

Update `search` to include daily summaries:

```python
    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        events = self.events_store.read()
        if not events and not self._has_summaries():
            return []
        if not query.strip():
            return []

        if self.embedding_model is None:
            results = self._search_by_keyword(query, events, top_k)
        else:
            results = self._search_by_embedding(query, events, top_k)

        summary_results = self._search_summaries(query, top_k=1)
        results.extend(summary_results)
        results.sort(key=lambda e: e.get("_score", 0), reverse=True)
        return results[:top_k]

    def _has_summaries(self) -> bool:
        summaries = self.summaries_store.read()
        return bool(summaries.get("daily_summaries"))

    def _search_summaries(self, query: str, top_k: int = 1) -> list[dict]:
        query_lower = query.lower()
        summaries = self.summaries_store.read()
        daily = summaries.get("daily_summaries", {})
        today = date.today()
        scored = []
        for d, s in daily.items():
            content = s.get("content", "")
            if query_lower not in content.lower():
                continue
            days_elapsed = (today - date.fromisoformat(s.get("last_recall_date", d))).days
            strength = s.get("memory_strength", 1)
            retention = forgetting_curve(days_elapsed, strength)
            scored.append((d, s, retention))

        scored.sort(key=lambda x: x[2], reverse=True)
        results = []
        for d, s, retention in scored[:top_k]:
            result = {
                "content": f"[摘要] {s['content']}",
                "date_group": d,
                "memory_strength": s.get("memory_strength", 1),
                "_source": "daily_summary",
                "_score": retention * SUMMARY_WEIGHT,
            }
            results.append(result)
            s["memory_strength"] += 1
            s["last_recall_date"] = today.isoformat()
        if scored:
            self.summaries_store.write(summaries)
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_bank.py::TestHierarchicalSummarization -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory_bank.py tests/test_memory_bank.py
git commit -m "feat(memorybank): implement hierarchical summarization"
```

---

### Task 6: Integrate into MemoryModule and Workflow

**Files:**
- Modify: `app/memory/memory.py`
- Modify: `app/agents/workflow.py`
- Modify: `app/storage/init_data.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests for memorybank mode in MemoryModule**

```python
# tests/test_memory.py (append)

def test_search_memorybank_mode(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    memory.write({"content": "下午3点会议", "type": "meeting"})
    results = memory.search("会议", mode="memorybank")
    assert len(results) > 0

def test_search_invalid_mode_raises(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    with pytest.raises(ValueError, match="Unknown mode"):
        memory.search("test", mode="nonexistent")
```

- [ ] **Step 2: Run tests to verify memorybank fails**

Run: `pytest tests/test_memory.py::test_search_memorybank_mode -v`
Expected: FAIL - ValueError "Unknown mode: memorybank"

- [ ] **Step 3: Add memorybank branch to MemoryModule**

Modify `app/memory/memory.py`:

1. Add import at top: `from app.memory.memory_bank import MemoryBankBackend`

2. Add `_memorybank_backend` attribute in `__init__`:
```python
    self._memorybank_backend: Optional[MemoryBankBackend] = None
```

3. Add new branch in `search()`:
```python
        elif mode == "memorybank":
            return self._search_by_memorybank(query)
```

4. Add method:
```python
    def _get_memorybank_backend(self) -> MemoryBankBackend:
        if self._memorybank_backend is None:
            self._memorybank_backend = MemoryBankBackend(
                self.data_dir,
                embedding_model=self.embedding_model,
                chat_model=self.chat_model,
            )
        return self._memorybank_backend

    def _search_by_memorybank(self, query: str) -> list:
        backend = self._get_memorybank_backend()
        return backend.search(query)
```

- [ ] **Step 4: Update init_storage for summaries file**

Add to `files` dict in `app/storage/init_data.py`:
```python
        "memorybank_summaries.json": {"daily_summaries": {}, "overall_summary": ""},
```

- [ ] **Step 5: Update workflow to use write_with_memory**

Modify `app/agents/workflow.py`:

1. Add import: `from app.memory.memory_bank import MemoryBankBackend`

2. In `_execution_node`, change the write call when `memory_mode == "memorybank"`:
```python
    def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision", {})
        content = decision.get("content", "无提醒内容")
        if self.memory_mode == "memorybank":
            backend = self._get_memorybank_backend()
            event_id = backend.write_with_memory(
                {"content": content, "type": "reminder", "decision": decision}
            )
        else:
            event_id = self.memory.write(
                {"content": content, "type": "reminder", "decision": decision}
            )
        ...
```

3. Add helper to `AgentWorkflow`:
```python
    def _get_memorybank_backend(self) -> MemoryBankBackend:
        from app.memory.memory_bank import MemoryBankBackend
        if not hasattr(self, '_memorybank_backend') or self._memorybank_backend is None:
            self._memorybank_backend = MemoryBankBackend(
                self.data_dir,
                embedding_model=getattr(self, '_embedding_model', None),
                chat_model=self.memory.chat_model,
            )
        return self._memorybank_backend
```

Also update `_build_graph` initialization to store embedding model when memory_mode is "memorybank":
```python
        if memory_mode == "memorybank":
            from app.models.embedding import EmbeddingModel
            self._embedding_model = EmbeddingModel()
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/test_memory.py tests/test_workflow.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add app/memory/memory.py app/agents/workflow.py app/storage/init_data.py tests/test_memory.py
git commit -m "feat(memorybank): integrate memorybank mode into MemoryModule and Workflow"
```

---

### Task 7: Experiment Runner Integration

**Files:**
- Modify: `app/experiment/runner.py`
- Test: `tests/test_experiment.py`

- [ ] **Step 1: Write failing test**

Check `tests/test_experiment.py` for existing valid_methods tests. Add or modify a test that verifies `memorybank` is a valid method.

- [ ] **Step 2: Update valid_methods set**

In `app/experiment/runner.py:216`, change:
```python
        valid_methods = {"keyword", "llm_only", "embeddings", "memorybank"}
```

And line 218:
```python
            methods = ["keyword", "llm_only", "embeddings", "memorybank"]
```

- [ ] **Step 3: Run experiment tests**

Run: `pytest tests/test_experiment.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/experiment/runner.py tests/test_experiment.py
git commit -m "feat(memorybank): add memorybank to experiment runner valid methods"
```

---

### Task 8: Lint and Final Verification

- [ ] **Step 1: Run linter**

Run: `ruff check app/ tests/`
Expected: No errors

- [ ] **Step 2: Run type checker (if configured)**

Run: `mypy app/ --ignore-missing-imports` or `ty check`
Expected: No new errors

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit (if any lint fixes)**

```bash
git add -A
git commit -m "chore: lint fixes for memorybank integration"
```
