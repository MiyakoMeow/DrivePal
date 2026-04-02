# Lock Usage Rules Compliance — Design Spec

## Background

AGENTS.md defines lock usage rules:

1. Only use `asyncio.Lock` in internal methods prefixed with `_locked_`
2. Never use locks directly in public API methods
3. Public APIs gain thread safety by calling corresponding `_locked_` methods
4. TOMLStore and similar底层存储's internal locks are exempt

Audit found 16 violations across 7 files.

## Approach

**Plan A: Minimal Refactor** — Mechanical extraction of lock logic into `_locked_` methods. No new abstractions. Two-phase lock patterns split into multiple `_locked_` methods. Public methods become orchestrators calling `_locked_` methods.

## Changes by File

### 1. `app/memory/components.py`

**FeedbackManager**:
- `_get_lock()` → `_locked_get_lock()`
- `update_feedback()` (public, uses lock directly):
  - Extract `_locked_update_feedback(feedback: FeedbackData)` — holds lock, calls `_write_feedback` + `_update_strategy`
  - Public `update_feedback()` becomes orchestrator

### 2. `app/memory/stores/memory_bank/summarization.py`

**SummaryManager**:

`strengthen_summaries()` (public):
- Extract `_locked_strengthen(matched_keys, today)` — holds lock, reads/writes summaries_store
- Public method checks empty → gets today → calls `_locked_strengthen`

`maybe_summarize()` (public, two-phase):
- Extract `_locked_check_summarize(date_group, count, latest_source_ts) → bool` — holds lock, checks if generation needed
- Extract `_locked_save_summary(date_group, summary_text, count, latest_source_ts) → bool` — holds lock, writes summary, returns whether overall update needed
- Public method orchestrates: pre-check → `_locked_check_summarize` → LLM call → `_locked_save_summary` → conditionally calls `update_overall_summary`

`update_overall_summary()` (public, two-phase):
- Extract `_locked_write_overall_summary(overall_text)` — holds lock, writes overall_summary
- Public method: pre-check → read data → LLM call → `_locked_write_overall_summary`

### 3. `app/memory/stores/memory_bank/personality.py`

**PersonalityManager**:

`strengthen()` (public):
- Extract `_locked_strengthen(matched_date_groups, today)` — holds lock, updates personality store
- Public method checks empty → gets today → calls `_locked_strengthen`

`maybe_summarize()` (public, two-phase):
- Extract `_locked_check_summarize(date_group, group_interactions, latest_source_ts) → tuple[bool, str]` — holds lock, returns (should_generate, combined_text)
- Extract `_locked_save_personality(date_group, summary_text, interaction_count, latest_source_ts) → bool` — holds lock, writes daily personality, returns whether overall needed
- Extract `_locked_write_overall_personality(overall_text)` — holds lock, writes overall_personality
- Public method orchestrates all three steps

### 4. `app/memory/stores/memochat/store.py`

**MemoChatStore**:

`write()` (public):
- Extract `_locked_write(memo_entry, event_copy)` — holds `_write_lock`, calls `_engine.append_memo` + `_storage.append_raw`
- Public method constructs data → calls `_locked_write`

`write_interaction()` (public):
- Extract `_locked_write_interaction(interaction)` — holds `_write_lock`, calls append_interaction + append_recent_dialog × 2
- Public method constructs data → calls `_locked_write_interaction` → calls `trigger_summarization()`

### 5. `app/memory/stores/memochat/engine.py`

**MemoChatEngine** (all internal):

| Current | New |
|---|---|
| `_ensure_initialized()` | `_locked_ensure_initialized()` |
| `append_memo()` | `_locked_append_memo()` |
| `_summarize_if_needed()` | `_locked_summarize_if_needed()` |

All callers updated accordingly.

### 6. `app/memory/stores/memory_bank/engine.py`

**MemoryBankEngine**:

`_strengthen_and_forget()` (internal, uses lock):
- Rename to `_locked_strengthen_and_forget()`

`_update_event_summary()` (internal, uses lock):
- Rename to `_locked_update_event_summary()`

`write_interaction()` (public, uses lock directly):
- Extract `_locked_write_interaction(interaction, today, interaction_id) → tuple[Optional[str], Optional[dict]]` — holds lock, performs append/associate logic, returns (append_event_id, new_event)
- Public method orchestrates: construct → `_locked_write_interaction` → conditionally `_locked_update_event_summary` → post-processing

### 7. `app/memory/memory.py`

**MemoryModule**:

`_get_store()` (internal, uses lock):
- Rename to `_locked_get_store()`
- Double-check locking pattern preserved

## Not Changed

- `app/storage/toml_store.py` — exempt (底层存储)
- `vendor/` — third-party code
- All public method signatures and external behavior remain identical
