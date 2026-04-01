# 记忆后端隔离重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MemoryBank 专属逻辑从 `components.py` 移至 `stores/memory_bank/` 目录，使 `components.py` 仅保留通用可复用组件。

**Architecture:** 按后端拆目录：`stores/memory_bank/` 包含 engine、personality、summarization 三个模块，通过组合模式组装。`components.py` 保留 EventStorage 等通用组件供所有后端复用。

**Tech Stack:** Python 3, asyncio, TOMLStore, pytest

**Spec:** `docs/superpowers/specs/2026-04-02-memory-backend-isolation-design.md`

---

### Task 1: 创建 stores/memory_bank/ 目录结构

**Files:**
- Create: `app/memory/stores/memory_bank/__init__.py`
- Create: `app/memory/stores/memory_bank/engine.py`（空文件占位）
- Create: `app/memory/stores/memory_bank/personality.py`（空文件占位）
- Create: `app/memory/stores/memory_bank/summarization.py`（空文件占位）
- Create: `app/memory/stores/memory_bank/store.py`（空文件占位）

- [ ] **Step 1: 创建目录和占位文件**

```bash
mkdir -p app/memory/stores/memory_bank
touch app/memory/stores/memory_bank/__init__.py
touch app/memory/stores/memory_bank/engine.py
touch app/memory/stores/memory_bank/personality.py
touch app/memory/stores/memory_bank/summarization.py
touch app/memory/stores/memory_bank/store.py
```

- [ ] **Step 2: 验证目录结构**

```bash
ls app/memory/stores/memory_bank/
```

Expected: `__init__.py  engine.py  personality.py  store.py  summarization.py`

- [ ] **Step 3: Commit**

```bash
git add app/memory/stores/memory_bank/
git commit -m "chore: scaffold memory_bank store directory structure"
```

---

### Task 2: 提取 PersonalityManager

**Files:**
- Create: `app/memory/stores/memory_bank/personality.py`
- Reference: `app/memory/components.py:422-483`（_search_personality, _strengthen_personality）
- Reference: `app/memory/components.py:642-739`（_maybe_summarize_personality, _generate_overall_personality_text）

**核心逻辑：** 从 `MemoryBankEngine` 中提取人格相关方法到独立 `PersonalityManager` 类。

- [ ] **Step 1: 编写 personality.py**

`PersonalityManager` 类包含：
- `__init__(self, data_dir: Path)` — 初始化 `_personality_store`（TOMLStore）和 `_personality_lock`
- `search(self, query: str, top_k: int) -> list[SearchResult]` — 从 `_search_personality` 搬入
- `strengthen(self, matched_date_groups: list[str]) -> None` — 从 `_strengthen_personality` 搬入
- `maybe_summarize(self, date_group: str, events: list[dict], interactions: list[dict], chat_model: ChatModel | None) -> None` — 从 `_maybe_summarize_personality` 搬入，参数改为接收 events 和 interactions 列表（而非内部读取）
- `generate_overall_text(self, personality_data: dict, chat_model: ChatModel | None) -> str | None` — 从 `_generate_overall_personality_text` 搬入

常量搬入：`PERSONALITY_SUMMARY_THRESHOLD`, `OVERALL_PERSONALITY_THRESHOLD`

- [ ] **Step 2: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/stores/memory_bank/personality.py
uv run ruff format app/memory/stores/memory_bank/personality.py
```

- [ ] **Step 3: Commit**

```bash
git add app/memory/stores/memory_bank/personality.py
git commit -m "feat(memory): extract PersonalityManager from MemoryBankEngine"
```

---

### Task 3: 提取 SummaryManager

**Files:**
- Create: `app/memory/stores/memory_bank/summarization.py`
- Reference: `app/memory/components.py:358-420`（_search_summaries, _strengthen_summaries）
- Reference: `app/memory/components.py:600-640`（_maybe_summarize）
- Reference: `app/memory/components.py:741-761`（_update_overall_summary）

**核心逻辑：** 从 `MemoryBankEngine` 中提取摘要相关方法到独立 `SummaryManager` 类。

- [ ] **Step 1: 编写 summarization.py**

`SummaryManager` 类包含：
- `__init__(self, data_dir: Path)` — 初始化 `_summaries_store`（TOMLStore）
- `search_summaries(self, query: str, daily_summaries: dict, top_k: int) -> list[SearchResult]` — 从 `_search_summaries` 搬入
- `strengthen_summaries(self, matched_keys: list[str], daily_summaries: dict) -> None` — 从 `_strengthen_summaries` 搬入
- `maybe_summarize(self, date_group: str, events: list[dict], chat_model: ChatModel | None) -> None` — 从 `_maybe_summarize` 搬入，参数改为接收 events 列表
- `update_overall_summary(self, daily_summaries: dict, chat_model: ChatModel | None) -> None` — 从 `_update_overall_summary` 搬入

常量搬入：`DAILY_SUMMARY_THRESHOLD`, `OVERALL_SUMMARY_THRESHOLD`, `SUMMARY_WEIGHT`

- [ ] **Step 2: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/stores/memory_bank/summarization.py
uv run ruff format app/memory/stores/memory_bank/summarization.py
```

- [ ] **Step 3: Commit**

```bash
git add app/memory/stores/memory_bank/summarization.py
git commit -m "feat(memory): extract SummaryManager from MemoryBankEngine"
```

---

### Task 4: 提取 MemoryBankEngine

**Files:**
- Create: `app/memory/stores/memory_bank/engine.py`
- Reference: `app/memory/components.py:155-314`（MemoryBankEngine 的 write/search/strengthen/soft_forget）
- Reference: `app/memory/components.py:485-556`（write_interaction, _should_append_to_event）

**核心逻辑：** 将 `MemoryBankEngine` 从 `components.py` 搬入 `engine.py`，内部委托 PersonalityManager 和 SummaryManager。

- [ ] **Step 1: 编写 engine.py**

`MemoryBankEngine` 类：
- `__init__(self, data_dir: Path, storage: EventStorage, embedding_model, chat_model)` — 创建 `_personality_mgr = PersonalityManager(data_dir)` 和 `_summary_mgr = SummaryManager(data_dir)`，保留 `_interactions_store`、`_lock`、`_storage`
- `write()` — 不变，但 `_maybe_summarize` 委托给 `_summary_mgr.maybe_summarize`
- `search()` — 不变，但 `_search_summaries` 委托给 `_summary_mgr.search_summaries`，`_search_personality` 委托给 `_personality_mgr.search`
- `write_interaction()` — 不变，但 `_maybe_summarize` 和 `_maybe_summarize_personality` 分别委托
- 保留：`_search_by_keyword`, `_search_by_embedding`, `_strengthen_events`, `_strengthen_interactions`, `_soft_forget_events`, `_expand_event_interactions`, `_should_append_to_event`, `_append_interaction_to_event`, `_update_event_summary`
- 删除：`_persist_interaction`（死代码，无任何调用点）

常量搬入：`AGGREGATION_SIMILARITY_THRESHOLD`, `TOP_K`, `SOFT_FORGET_THRESHOLD`, `SOFT_FORGET_STRENGTH`

**关键：** `_personality_store` 和 `_summaries_store` 属性通过 manager 暴露（供 store.py 的 property 访问）：
- `engine._personality_mgr._personality_store` 替代原来的 `engine._personality_store`
- `engine._summary_mgr._summaries_store` 替代原来的 `engine._summaries_store`

- [ ] **Step 2: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/stores/memory_bank/engine.py
uv run ruff format app/memory/stores/memory_bank/engine.py
```

- [ ] **Step 3: Commit**

```bash
git add app/memory/stores/memory_bank/engine.py
git commit -m "feat(memory): extract MemoryBankEngine to dedicated module"
```

---

### Task 5: 编写 store.py 和 __init__.py

**Files:**
- Create: `app/memory/stores/memory_bank/store.py`
- Create: `app/memory/stores/memory_bank/__init__.py`

**核心逻辑：** 从 `stores/memory_bank_store.py` 搬入，更新导入路径。属性访问路径同步更新。

- [ ] **Step 1: 编写 store.py**

与原 `memory_bank_store.py` 逻辑完全一致，仅更新导入：
- `from app.memory.stores.memory_bank.engine import MemoryBankEngine`
- `from app.memory.components import EventStorage, FeedbackManager`

更新 property 访问路径：
- `summaries_store` → `self._engine._summary_mgr._summaries_store`
- `interactions_store` → `self._engine._interactions_store`（不变）

- [ ] **Step 2: 编写 __init__.py**

```python
from app.memory.stores.memory_bank.store import MemoryBankStore

__all__ = ["MemoryBankStore"]
```

- [ ] **Step 3: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/stores/memory_bank/store.py app/memory/stores/memory_bank/__init__.py
uv run ruff format app/memory/stores/memory_bank/store.py app/memory/stores/memory_bank/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add app/memory/stores/memory_bank/store.py app/memory/stores/memory_bank/__init__.py
git commit -m "feat(memory): add MemoryBankStore to new directory structure"
```

---

### Task 6: 清理 components.py

**Files:**
- Modify: `app/memory/components.py`

**核心逻辑：** 删除所有已搬出的 MemoryBank 专属代码，仅保留通用组件。

- [ ] **Step 1: 清理 components.py**

保留：
- `forgetting_curve()` 函数（通用工具，engine 依赖它）
- `EventStorage` 类
- `KeywordSearch` 类
- `_strategy_locks`, `_strategy_locks_lock`
- `FeedbackManager` 类
- `SimpleInteractionWriter` 类

删除：
- 所有 MemoryBank 专属常量（`PERSONALITY_SUMMARY_THRESHOLD`, `OVERALL_PERSONALITY_THRESHOLD`, `AGGREGATION_SIMILARITY_THRESHOLD`, `DAILY_SUMMARY_THRESHOLD`, `OVERALL_SUMMARY_THRESHOLD`, `SUMMARY_WEIGHT`, `TOP_K`, `SOFT_FORGET_THRESHOLD`, `SOFT_FORGET_STRENGTH`）
- `logger`（仅 MemoryBank 使用）
- `MemoryBankEngine` 类整体
- `logging` import（如果不再需要）

- [ ] **Step 2: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/components.py
uv run ruff format app/memory/components.py
```

- [ ] **Step 3: Commit**

```bash
git add app/memory/components.py
git commit -m "refactor(memory): clean components.py, keep only reusable components"
```

---

### Task 7: 更新 memory.py 注册表

**Files:**
- Modify: `app/memory/memory.py:28-31`

- [ ] **Step 1: 更新导入路径**

```python
def _import_all_stores() -> None:
    from app.memory.stores.memory_bank import MemoryBankStore

    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
```

- [ ] **Step 2: 运行 lint 检查**

```bash
uv run ruff check --fix app/memory/memory.py
uv run ruff format app/memory/memory.py
```

- [ ] **Step 3: Commit**

```bash
git add app/memory/memory.py
git commit -m "refactor(memory): update store registry import path"
```

---

### Task 8: 删除旧文件并更新其余导入

**Files:**
- Delete: `app/memory/stores/memory_bank_store.py`
- Modify: `app/memory/stores/__init__.py`
- Modify: `adapters/memory_adapters/memory_bank_adapter.py`
- Modify: `tests/test_embedding.py`

- [ ] **Step 1: 删除旧文件**

```bash
git rm app/memory/stores/memory_bank_store.py
```

- [ ] **Step 2: 更新 stores/__init__.py**

```python
from app.memory.stores.memory_bank import MemoryBankStore
```

- [ ] **Step 3: 更新 adapters/memory_adapters/memory_bank_adapter.py**

导入路径：`from app.memory.stores.memory_bank_store import MemoryBankStore` → `from app.memory.stores.memory_bank import MemoryBankStore`

- [ ] **Step 4: 更新 tests/test_embedding.py**

导入路径：`from app.memory.stores.memory_bank_store import MemoryBankStore` → `from app.memory.stores.memory_bank import MemoryBankStore`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(memory): remove old memory_bank_store.py and update all imports"
```

---

### Task 9: 更新测试导入路径

**Files:**
- Modify: `tests/test_components.py`
- Modify: `tests/test_memory_bank.py`
- Modify: `tests/stores/test_memory_bank_store.py`
- Modify: `tests/test_memory_store_contract.py`

**核心逻辑：** 所有导入从 `app.memory.components` 改为新的模块路径。

- [ ] **Step 1: 更新 test_components.py**

关键变更：
- `from app.memory.components import MemoryBankEngine` → `from app.memory.stores.memory_bank.engine import MemoryBankEngine`
- `from app.memory.components import SOFT_FORGET_THRESHOLD, SOFT_FORGET_STRENGTH` → `from app.memory.stores.memory_bank.engine import SOFT_FORGET_THRESHOLD, SOFT_FORGET_STRENGTH`
- 保留：`EventStorage`, `KeywordSearch`, `FeedbackManager`, `SimpleInteractionWriter`, `forgetting_curve` 仍从 `app.memory.components` 导入
- 属性访问路径：`engine._personality_store` → `engine._personality_mgr._personality_store`（4 处：行 375, 392, 412, 430）

- [ ] **Step 2: 更新 test_memory_bank.py**

关键变更：
- `from app.memory.components import DAILY_SUMMARY_THRESHOLD, OVERALL_SUMMARY_THRESHOLD` → `from app.memory.stores.memory_bank.summarization import DAILY_SUMMARY_THRESHOLD, OVERALL_SUMMARY_THRESHOLD`
- `from app.memory.stores.memory_bank_store import MemoryBankStore` → `from app.memory.stores.memory_bank import MemoryBankStore`
- `backend._engine._update_overall_summary(summaries["daily_summaries"], summaries)` → `backend._engine._summary_mgr.update_overall_summary(summaries["daily_summaries"], summaries)`（行 121）

- [ ] **Step 3: 更新 tests/stores/test_memory_bank_store.py**

关键变更：
- `from app.memory.stores.memory_bank_store import MemoryBankStore` → `from app.memory.stores.memory_bank import MemoryBankStore`
- `store.summaries_store` → 需确认 engine 内部 `_summary_mgr._summaries_store` 路径；如果 store.py 暴露了 `summaries_store` property 则无需改测试代码

- [ ] **Step 4: 更新 test_memory_store_contract.py**

此文件通过 `MemoryModule` facade 访问 store，理论上不受影响。验证即可。

- [ ] **Step 5: 运行 lint 检查**

```bash
uv run ruff check --fix tests/
uv run ruff format tests/
```

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test(memory): update import paths for new directory structure"
```

---

### Task 10: 运行全部测试并修复

**Files:**
- 可能修改：任何因路径变更导致的测试失败

- [ ] **Step 1: 运行类型检查**

```bash
uv run ty check
```

- [ ] **Step 2: 运行 lint**

```bash
uv run ruff check --fix
uv run ruff format
```

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 4: 修复任何失败，然后 Commit**

```bash
git add -A
git commit -m "fix(memory): resolve test failures after restructuring"
```
