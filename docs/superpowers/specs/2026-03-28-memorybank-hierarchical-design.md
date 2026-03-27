# MemoryBank Hierarchical Memory Structure Design

## Overview

Upgrade the existing `MemoryBankBackend` from flat event storage to a three-tier hierarchical structure: **Interaction → Event → Summary**. Inspired by the [MemoryBank-SiliconFriend](https://github.com/zhongwanjun/MemoryBank-SiliconFriend) repository's `memory.json` format.

Goals:

1. Preserve raw conversation history (interactions) for richer context retrieval
2. Maintain event-level aggregation for efficient search with forgetting-curve scoring
3. Keep the existing summary layer unchanged
4. Zero impact on non-memorybank retrieval modes (keyword/llm_only/embeddings)

## Data Model

### Three-Tier Structure

```
Interaction (raw conversation)
  ├── id: str              (e.g. "20260328120000_a1b2c3d4")
  ├── event_id: str        (parent event reference)
  ├── query: str           (user input)
  ├── response: str        (system reply)
  ├── timestamp: str       (ISO 8601)
  ├── memory_strength: int (initial 1, +1 on retrieval hit)
  └── last_recall_date: str (ISO date, updated on retrieval hit)
        │
        ▼ aggregated into
Event (semantic summary)
  ├── id: str
  ├── content: str         (LLM-generated summary of interactions)
  ├── type: str            (meeting/travel/shopping/contact/...)
  ├── interaction_ids: list[str]  (child interaction references)
  ├── created_at: str
  ├── updated_at: str      (updated when new interaction appended)
  ├── memory_strength: int (initial 1)
  ├── last_recall_date: str
  └── date_group: str      (ISO date, derived from created_at)
        │
        ▼ aggregated into
Summary (hierarchical, unchanged)
  ├── daily_summaries: {date: {content, memory_strength, last_recall_date, event_count}}
  └── overall_summary: str
```

### Storage Files

| File | Type | Description |
|------|------|-------------|
| `data/interactions.json` | **New** | List of interaction records |
| `data/events.json` | Modified | Added `interaction_ids: list[str]` and `updated_at: str` |
| `data/memorybank_summaries.json` | Unchanged | Daily and overall summaries |

### Interaction Data Example

```json
[
  {
    "id": "20260328120000_a1b2c3d4",
    "event_id": "20260328120000_e5f6g7h8",
    "query": "提醒我明天上午9点开会",
    "response": "好的，已为您添加明天上午9点的会议提醒。",
    "timestamp": "2026-03-28T12:00:00",
    "memory_strength": 1,
    "last_recall_date": "2026-03-28"
  }
]
```

### Event Data Example (modified)

```json
[
  {
    "id": "20260328120000_e5f6g7h8",
    "content": "用户添加了明天上午9点的会议提醒，后来改为下午2点",
    "type": "reminder",
    "interaction_ids": [
      "20260328120000_a1b2c3d4",
      "20260328130000_b2c3d4e5"
    ],
    "created_at": "2026-03-28T12:00:00",
    "updated_at": "2026-03-28T13:00:00",
    "memory_strength": 2,
    "last_recall_date": "2026-03-28",
    "date_group": "2026-03-28"
  }
]
```

## Aggregation Strategy

### When a new interaction arrives:

1. **Single interaction** (first interaction ever, or no recent event): Create a new event with `content = interaction.query` (no LLM call needed)
2. **Append to existing event**: If the most recent event's `content` has cosine similarity > 0.8 with `interaction.query` (or keyword overlap fallback), append the interaction to that event and update `event.content` via LLM summary
3. **Create new event**: If similarity is below threshold, create a new event

### Event content update:

When interactions are appended to an existing event:
- Collect all child interactions' `query` + `response` text
- LLM prompt: "请简洁总结以下交互记录（一句话）:\n{combined_text}"
- Update `event.content` and `event.updated_at`

## Retrieval Flow (memorybank mode)

```
query input
  │
  ├─1. Event-level retrieval (existing logic, unchanged)
  │     encode query → for each event:
  │       score = cosine_similarity * forgetting_curve(days_elapsed, strength)
  │     return top-k events
  │
  ├─2. Summary-level retrieval (existing logic, unchanged)
  │     keyword match daily_summaries, weight * 0.8
  │
  ├─3. Merge & rank
  │     events + summaries → sort by _score desc → take top_k
  │
  └─4. Expand results
        for each matched event:
          look up interactions where interaction.event_id == event.id
          attach interactions list to result
        return: {event fields..., interactions: [{query, response, ...}]}
```

### Strengthening on hit:

- Matched event: `memory_strength += 1`, `last_recall_date = today`
- All interactions under matched event: `memory_strength += 1`, `last_recall_date = today`

## Write Flow (memorybank mode)

```
conversation complete (query + response available)
  │
  ├─1. Write interaction
  │     interaction = {id, event_id: TBD, query, response, timestamp, memory_strength: 1}
  │     interactions_store.append(interaction)
  │
  ├─2. Event aggregation
  │     _should_append_to_event(interaction):
  │       recent event with same date_group?
  │         compute similarity(recent_event.content, interaction.query)
  │         if embedding_model available: cosine > 0.8 → append
  │         else: keyword overlap in content → append
  │       return event_id or None
  │
  │     if event_id returned:
  │       append interaction.id to event.interaction_ids
  │       _update_event_summary(event_id)
  │       interaction.event_id = event_id
  │     else:
  │       create new event (content = interaction.query, interaction_ids = [interaction.id])
  │       interaction.event_id = new_event.id
  │
  └─3. Persist updated interaction (with correct event_id)
        persist updated events store
        trigger summarization check (existing logic)
```

## Interface Changes

### MemoryBankBackend

```python
class MemoryBankBackend:
    # Existing (unchanged)
    def search(self, query: str, top_k: int = 3) -> list[dict]: ...
    def write_with_memory(self, event: dict) -> str: ...

    # New
    def write_interaction(self, query: str, response: str) -> str:
        """Write raw interaction, auto-handle event aggregation. Returns interaction_id."""

    # New internal
    def _should_append_to_event(self, interaction: dict) -> Optional[str]:
        """Determine which event to append to. Returns event_id or None."""

    def _update_event_summary(self, event_id: str) -> None:
        """Re-generate event content summary via LLM from child interactions."""

    def _expand_event_interactions(self, events: list[dict]) -> list[dict]:
        """Look up and attach interaction lists to matched events."""
```

### MemoryModule

```python
class MemoryModule:
    # New delegate
    def write_interaction(self, query: str, response: str) -> str:
        """Delegate to MemoryBankBackend.write_interaction()"""

    # Modified: memorybank branch returns results with interactions
    def _search_by_memorybank(self, query: str) -> list: ...
```

### AgentWorkflow

```python
# _execution_node: memorybank mode uses write_interaction
if self.memory_mode == "memorybank":
    event_id = self.memory.write_interaction(user_input, result)
else:
    event_id = self.memory.write(event_data)
```

## File Changes

| File | Action | Scope |
|------|--------|-------|
| `app/memory/memory_bank.py` | Major modification | Add interaction layer, aggregation logic, result expansion |
| `app/memory/memory.py` | Minor modification | Add `write_interaction()` delegate, update memorybank search to include interactions |
| `app/agents/workflow.py` | Minor modification | Use `write_interaction()` in memorybank execution node |
| `app/storage/init_data.py` | Minor modification | Initialize `interactions.json` |
| `tests/test_memory_bank.py` | Extend | Tests for interaction write, aggregation, expansion |
| `tests/test_memory.py` | Extend | Memorybank mode with interaction tests |
| `tests/test_integration.py` | Extend | End-to-end memorybank with interaction return |

## Backward Compatibility

- Non-memorybank modes (keyword/llm_only/embeddings): zero changes, unaffected
- Existing `events.json` data: legacy events without `interaction_ids` field work as-is (treated as events with empty interaction list)
- `write_with_memory()`: preserved for backward compatibility; new code paths use `write_interaction()`

## Unresolved Questions

None.
