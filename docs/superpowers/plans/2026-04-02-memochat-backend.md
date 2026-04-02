# MemoChat 后端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MemoChat 论文的三阶段记忆 pipeline 实现为知情车秘的独立 MemoryStore 后端。

**Architecture:** 在 `app/memory/stores/memochat/` 下新建独立后端，通过 Protocol 结构化子类型满足 `MemoryStore` 接口，通过 Registry 注册为 `MemoryMode.MEMOCHAT`。核心引擎实现 summarization→retrieval 三阶段 pipeline，检索策略通过 `RetrievalMode` 枚举切换。

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, TOMLStore (现有), asyncio, prompt engineering (现有 ChatModel)

**Spec:** `docs/superpowers/specs/2026-04-02-memochat-backend-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/memory/stores/memochat/__init__.py` | 模块导出 |
| Create | `app/memory/stores/memochat/prompts.py` | Prompt 模板（writing + retrieval） |
| Create | `app/memory/stores/memochat/retriever.py` | RetrievalMode 枚举 + 两种检索策略实现 |
| Create | `app/memory/stores/memochat/engine.py` | MemoChatEngine（三阶段 pipeline） |
| Create | `app/memory/stores/memochat/store.py` | MemoChatStore（MemoryStore Protocol 实现） |
| Modify | `app/memory/types.py` | 新增 `MEMOCHAT` 枚举值 |
| Modify | `app/memory/memory.py` | 注册 MemoChatStore |
| Create | `tests/stores/test_memochat_prompts.py` | Prompt 模板测试 |
| Create | `tests/stores/test_memochat_retriever.py` | 检索策略测试 |
| Create | `tests/stores/test_memochat_engine.py` | 引擎测试 |
| Create | `tests/stores/test_memochat_store.py` | Store 级别测试 |
| Modify | `tests/test_memory_types.py` | 更新枚举测试 |
| Modify | `tests/test_memory_store_contract.py` | 添加 memochat 到契约测试参数 |

参考文件（只读）：
- `app/memory/interfaces.py` — MemoryStore Protocol 定义
- `app/memory/schemas.py` — MemoryEvent, SearchResult, FeedbackData
- `app/memory/components.py` — EventStorage, FeedbackManager, forgetting_curve
- `app/memory/stores/memory_bank/personality.py` — PersonalityManager
- `app/memory/stores/memory_bank/store.py` — 参考实现模式
- `app/memory/stores/memory_bank/engine.py` — 参考引擎模式
- `app/storage/toml_store.py` — TOMLStore 接口
- `app/memory/utils.py` — cosine_similarity
- `/tmp/MemoChat/code/codes/api/gpt_memochat.py` — MemoChat 原始 pipeline
- `/tmp/MemoChat/data/prompts.json` — 原始 prompt 模板

---

### Task 1: RetrievalMode 枚举与 Prompt 模板

**Files:**
- Create: `app/memory/stores/memochat/__init__.py`
- Create: `app/memory/stores/memochat/prompts.py`
- Create: `app/memory/stores/memochat/retriever.py`
- Create: `tests/stores/test_memochat_prompts.py`

- [ ] **Step 1: 创建模块 `__init__.py`**

```python
"""MemoChat 记忆存储模块."""
```

- [ ] **Step 2: 写 prompts 测试**

`tests/stores/test_memochat_prompts.py`:
```python
"""MemoChat prompt 模板测试."""

from app.memory.stores.memochat.prompts import (
    RETRIEVAL_INSTRUCTION,
    RETRIEVAL_SYSTEM,
    WRITING_INSTRUCTION,
    WRITING_SYSTEM,
)


def test_writing_system_contains_line_placeholder() -> None:
    assert "LINE" in WRITING_SYSTEM


def test_writing_instruction_contains_json_keys() -> None:
    for key in ("topic", "summary", "start", "end"):
        assert key in WRITING_INSTRUCTION


def test_retrieval_system_contains_option_placeholder() -> None:
    assert "OPTION" in RETRIEVAL_SYSTEM


def test_retrieval_instruction_mentions_noto() -> None:
    assert "NOTO" in RETRIEVAL_INSTRUCTION


def test_retrieval_instruction_mentions_separator() -> None:
    assert "#" in RETRIEVAL_INSTRUCTION
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/stores/test_memochat_prompts.py -v`
Expected: FAIL (import error)

- [ ] **Step 4: 实现 `prompts.py`**

`app/memory/stores/memochat/prompts.py`:
```python
"""MemoChat prompt 模板，参考 MemoChat data/prompts.json 适配中文车舱场景."""

WRITING_SYSTEM = (
    "你将看到一段 LINE 行的任务对话（用户和机器人之间）。"
    "请阅读、记忆并理解任务对话，然后在任务介绍的指导下完成任务。"
)

WRITING_INSTRUCTION = """

```
任务介绍：
基于任务对话，执行以下操作：
1 - 归纳对话中所有可能的主题，用简短的词组表示。
2 - 确定每个主题的对话范围。这些范围应该是一组不相交、首尾相连的区间。
3 - 归纳每个主题下对话的摘要，用简短的句子概括。
4 - 以 JSON 格式报告主题、摘要和范围结果，仅使用指定的键：'topic', 'summary', 'start', 'end'。
例如，假设一段 M 行对话从第 1 行到第 N 行讨论"香蕉"，然后从第 N+1 行到第 M 行讨论"芒果"。
那么任务结果为：[{"topic": "香蕉", "summary": "用户和机器人讨论了香蕉。", "start": 1, "end": N}, {"topic": "芒果", "summary": "机器人给用户带来了芒果。", "start": N+1, "end": M}]。
注意事项：
1 - 对于每个 JSON 元素，'end' 的值应大于 'start' 的值，且两者都应大于 0 但不超过对话总行数 LINE。
2 - 相交区间如 {"topic": "苹果", "start": K, "end": N} 和 {"topic": "梨", "start": N-2, "end": M} 是非法的。
```

任务结果："""

RETRIEVAL_SYSTEM = (
    "你将看到 1 个查询语句和 OPTION 个主题选项。"
    "请阅读、记忆并理解给定材料，然后在任务介绍的指导下完成任务。"
    "\n"
)

RETRIEVAL_INSTRUCTION = """

```
任务介绍：
从主题选项中选择一个或多个与查询语句相关的主题。
注意有一个 NOTO 选项，如果所有其他主题选项都与查询语句无关，请选择它。
不要报告选项内容，只报告选中的选项编号，用 '#' 分隔的字符串表示。
例如，如果选择了主题选项 N 和 M，则输出为：N#M。
对于查询语句，任何选中的选项编号应大于 0 但不超过主题选项总数 OPTION。
```

任务结果："""
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/stores/test_memochat_prompts.py -v`
Expected: PASS

- [ ] **Step 6: 写 retriever 枚举测试**

在 `tests/stores/test_memochat_prompts.py` 末尾追加：
```python
from app.memory.stores.memochat.retriever import RetrievalMode


def test_retrieval_mode_values() -> None:
    assert RetrievalMode.FULL_LLM == "full_llm"
    assert RetrievalMode.HYBRID == "hybrid"


def test_retrieval_mode_is_str() -> None:
    assert isinstance(RetrievalMode.FULL_LLM, str)
```

- [ ] **Step 7: 运行测试验证失败**

Run: `uv run pytest tests/stores/test_memochat_prompts.py::test_retrieval_mode_values -v`
Expected: FAIL

- [ ] **Step 8: 实现 `retriever.py`（仅枚举，检索逻辑在 Task 3）**

`app/memory/stores/memochat/retriever.py`:
```python
"""MemoChat 检索策略."""

from enum import StrEnum


class RetrievalMode(StrEnum):
    """检索模式枚举."""

    FULL_LLM = "full_llm"
    HYBRID = "hybrid"
```

- [ ] **Step 9: 运行测试验证通过**

Run: `uv run pytest tests/stores/test_memochat_prompts.py -v`
Expected: PASS

- [ ] **Step 10: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 11: 提交**

```bash
git add app/memory/stores/memochat/ tests/stores/test_memochat_prompts.py
git commit -m "feat(memochat): add prompt templates and RetrievalMode enum"
```

---

### Task 2: MemoChatEngine — Summarization 阶段

**Files:**
- Create: `app/memory/stores/memochat/engine.py`
- Create: `tests/stores/test_memochat_engine.py`

- [ ] **Step 1: 写 summarization 测试**

`tests/stores/test_memochat_engine.py`:
```python
"""MemoChatEngine 测试."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.stores.memochat.engine import (
    MAX_LEN,
    MemoChatEngine,
    RECENT_DIALOGS_KEEP_AFTER_SUMMARY,
    SUMMARIZATION_CHAR_THRESHOLD,
    SUMMARIZATION_TURN_THRESHOLD,
)
from app.memory.stores.memochat.retriever import RetrievalMode


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock()
    return chat


@pytest.fixture
def mock_embedding() -> MagicMock:
    emb = MagicMock()
    emb.encode = AsyncMock(return_value=[0.1] * 10)
    emb.batch_encode = AsyncMock(return_value=[[0.1] * 10])
    return emb


@pytest.fixture
def engine(tmp_path: Path, mock_chat: MagicMock, mock_embedding: MagicMock) -> MemoChatEngine:
    return MemoChatEngine(tmp_path, mock_chat, mock_embedding, RetrievalMode.FULL_LLM)


class TestInit:
    async def test_recent_dialogs_initialized_on_empty(self, tmp_path: Path) -> None:
        eng = MemoChatEngine(tmp_path, MagicMock(), None, RetrievalMode.FULL_LLM)
        dialogs = await eng.read_recent_dialogs()
        assert len(dialogs) == 2
        assert dialogs[0].startswith("user:")
        assert dialogs[1].startswith("bot:")

    async def test_recent_dialogs_not_overwritten_if_exist(
        self, tmp_path: Path, mock_chat: MagicMock
    ) -> None:
        eng = MemoChatEngine(tmp_path, mock_chat, None, RetrievalMode.FULL_LLM)
        await eng.append_recent_dialog("user: test")
        eng2 = MemoChatEngine(tmp_path, mock_chat, None, RetrievalMode.FULL_LLM)
        dialogs = await eng2.read_recent_dialogs()
        assert any("test" in d for d in dialogs)


class TestAppendRecentDialog:
    async def test_appends_to_dialogs(self, engine: MemoChatEngine) -> None:
        await engine.append_recent_dialog("user: 你好")
        dialogs = await engine.read_recent_dialogs()
        assert "user: 你好" in dialogs


class TestSummarizeIfNeeded:
    async def test_no_summary_below_threshold(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        for i in range(3):
            await engine.append_recent_dialog(f"user: 短消息{i}")
        await engine._summarize_if_needed()
        mock_chat.generate.assert_not_called()

    async def test_triggers_summary_on_turn_count(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = json.dumps([
            {"topic": "测试", "summary": "简短摘要", "start": 1, "end": 3}
        ])
        dialogs = await engine.read_recent_dialogs()
        while len(dialogs) < SUMMARIZATION_TURN_THRESHOLD:
            await engine.append_recent_dialog("user: 填充内容")
            dialogs = await engine.read_recent_dialogs()
        await engine._summarize_if_needed()
        mock_chat.generate.assert_called_once()
        dialogs_after = await engine.read_recent_dialogs()
        assert len(dialogs_after) == RECENT_DIALOGS_KEEP_AFTER_SUMMARY

    async def test_writes_memos_on_summary(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = json.dumps([
            {"topic": "天气", "summary": "用户讨论了天气", "start": 1, "end": 2}
        ])
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 今天天气不错{i}")
        await engine._summarize_if_needed()
        memos = await engine.read_memos()
        assert "天气" in memos

    async def test_fallback_noto_on_parse_failure(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "无法解析的文本"
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 内容{i}")
        await engine._summarize_if_needed()
        memos = await engine.read_memos()
        assert "NOTO" in memos
        assert len(memos["NOTO"]) > 0

    async def test_no_truncation_on_llm_error(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.side_effect = RuntimeError("LLM unavailable")
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 内容{i}")
        dialogs_before = await engine.read_recent_dialogs()
        await engine._summarize_if_needed()
        dialogs_after = await engine.read_recent_dialogs()
        assert len(dialogs_after) == len(dialogs_before)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/stores/test_memochat_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `engine.py`（summarization 部分）**

`app/memory/stores/memochat/engine.py`:
```python
"""MemoChatEngine: 三阶段记忆 pipeline 引擎."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.memory.components import EventStorage
from app.memory.stores.memochat.prompts import (
    RETRIEVAL_INSTRUCTION,
    RETRIEVAL_SYSTEM,
    WRITING_INSTRUCTION,
    WRITING_SYSTEM,
)
from app.memory.stores.memochat.retriever import RetrievalMode
from app.storage.toml_store import TOMLStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

MAX_LEN = 2048
TARGET_LEN = 512
SUMMARIZATION_CHAR_THRESHOLD = MAX_LEN // 2
SUMMARIZATION_TURN_THRESHOLD = 10
RECENT_DIALOGS_KEEP_AFTER_SUMMARY = 2

_DEFAULT_GREETINGS = ["user: 你好！", "bot: 你好！我是你的行车助手。"]


def _normalize_model_outputs(text: str) -> list[dict]:
    """从 LLM 输出中提取 [{topic, summary, start, end}] 结构."""
    elements = [
        re.sub(r"\s+", " ", m.replace('"', "").replace("'", ""))
        for m in re.findall(r"'[^']*'|\"[^\"]*\"|\d+", text)
    ]
    results = []
    i = 0
    while i + 7 < len(elements):
        if (
            elements[i] == "topic"
            and elements[i + 2] == "summary"
            and elements[i + 4] == "start"
            and elements[i + 6] == "end"
        ):
            try:
                results.append({
                    "topic": elements[i + 1],
                    "summary": elements[i + 3],
                    "start": int(elements[i + 5]),
                    "end": int(elements[i + 7]),
                })
            except (ValueError, IndexError):
                pass
        i += 1
    return results


def _parse_json_outputs(text: str) -> list[dict]:
    """尝试 JSON 解析，失败则走正则提取."""
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [
                d for d in data
                if isinstance(d, dict) and "topic" in d and "summary" in d
            ]
    except (json.JSONDecodeError, TypeError):
        pass
    return _normalize_model_outputs(text)


class MemoChatEngine:
    """MemoChat 三阶段 pipeline 引擎."""

    def __init__(
        self,
        data_dir: Path,
        chat_model: Optional["ChatModel"] = None,
        embedding_model: Optional["EmbeddingModel"] = None,
        retrieval_mode: RetrievalMode = RetrievalMode.FULL_LLM,
    ) -> None:
        self.data_dir = data_dir
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.retrieval_mode = retrieval_mode
        self._storage = EventStorage(data_dir)
        self._dialogs_store = TOMLStore(
            data_dir, Path("memochat_recent_dialogs.toml"), list
        )
        self._memos_store = TOMLStore(
            data_dir, Path("memochat_memos.toml"), dict
        )
        self._interactions_store = TOMLStore(
            data_dir, Path("memochat_interactions.toml"), list
        )
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        dialogs = await self._dialogs_store.read()
        if not dialogs:
            await self._dialogs_store.write(list(_DEFAULT_GREETINGS))
        self._initialized = True

    async def read_recent_dialogs(self) -> list[str]:
        await self._ensure_initialized()
        return list(await self._dialogs_store.read())

    async def append_recent_dialog(self, text: str) -> None:
        await self._ensure_initialized()
        await self._dialogs_store.append(text)

    async def read_memos(self) -> dict:
        return dict(await self._memos_store.read())

    async def _write_memos(self, memos: dict) -> None:
        await self._memos_store.write(memos)

    async def read_interactions(self) -> list[dict]:
        return list(await self._interactions_store.read())

    async def _should_summarize(self, dialogs: list[str]) -> bool:
        if len(dialogs) < SUMMARIZATION_TURN_THRESHOLD:
            char_count = sum(len(d) for d in dialogs)
            if char_count <= SUMMARIZATION_CHAR_THRESHOLD:
                return False
        return True

    async def _summarize_if_needed(self) -> None:
        dialogs = await self.read_recent_dialogs()
        if not await self._should_summarize(dialogs):
            return
        if not self.chat_model:
            return
        dialogs_to_summarize = dialogs[2:]
        if not dialogs_to_summarize:
            return
        numbered = "\n".join(
            f"(line {i + 1}) {d.replace(chr(10), ' ')}"
            for i, d in enumerate(dialogs_to_summarize)
        )
        line_count = str(len(dialogs_to_summarize))
        system = WRITING_SYSTEM.replace("LINE", line_count)
        task_case = (
            f"\n\n```\n任务对话：\n{numbered}\n```"
            + WRITING_INSTRUCTION.replace("LINE", line_count)
        )
        prompt = system + task_case
        try:
            raw_output = await self.chat_model.generate(prompt)
        except Exception:
            logger.warning("Summarization LLM call failed, skipping")
            return
        parsed = _parse_json_outputs(raw_output)
        memos = await self.read_memos()
        if parsed:
            for entry in parsed:
                topic = entry.get("topic", "NOTO")
                start = max(entry.get("start", 1) - 1, 0)
                end = min(entry.get("end", len(dialogs_to_summarize)), len(dialogs_to_summarize))
                memo_entry = {
                    "id": self._storage.generate_id(),
                    "summary": entry.get("summary", ""),
                    "dialogs": dialogs_to_summarize[start:end],
                    "created_at": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                    "memory_strength": 1,
                    "last_recall_date": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).date().isoformat(),
                }
                memos.setdefault(topic, []).append(memo_entry)
        else:
            from random import sample
            count = min(2, len(dialogs_to_summarize))
            indices = sample(range(len(dialogs_to_summarize)), count)
            memos.setdefault("NOTO", []).append({
                "id": self._storage.generate_id(),
                "summary": f"部分对话内容: {' 或 '.join(dialogs_to_summarize[i] for i in indices)}",
                "dialogs": dialogs_to_summarize,
                "created_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "memory_strength": 1,
                "last_recall_date": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).date().isoformat(),
            })
        async with self._lock:
            await self._write_memos(memos)
            truncated = dialogs[-RECENT_DIALOGS_KEEP_AFTER_SUMMARY:]
            await self._dialogs_store.write(truncated)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/stores/test_memochat_engine.py -v`
Expected: PASS

- [ ] **Step 5: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 6: 提交**

```bash
git add app/memory/stores/memochat/engine.py tests/stores/test_memochat_engine.py
git commit -m "feat(memochat): implement summarization stage"
```

---

### Task 3: MemoChatEngine — Retrieval 阶段

**Files:**
- Modify: `app/memory/stores/memochat/engine.py`
- Modify: `app/memory/stores/memochat/retriever.py`
- Modify: `tests/stores/test_memochat_engine.py`
- Create: `tests/stores/test_memochat_retriever.py`

- [ ] **Step 1: 写 retriever 策略测试**

`tests/stores/test_memochat_retriever.py`:
```python
"""MemoChat 检索策略测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.stores.memochat.retriever import (
    retrieve_full_llm,
    retrieve_hybrid,
)


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock()
    return chat


@pytest.fixture
def mock_embedding() -> MagicMock:
    emb = MagicMock()
    emb.encode = AsyncMock(return_value=[0.1] * 10)
    emb.batch_encode = AsyncMock(return_value=[[0.1] * 10, [0.9] * 10, [0.1] * 10])
    return emb


MEMOS_SAMPLE = {
    "天气": [
        {"id": "id1", "summary": "用户讨论了天气", "dialogs": ["user: 今天天气不错"]},
    ],
    "会议": [
        {"id": "id2", "summary": "用户有会议安排", "dialogs": ["user: 明天开会"]},
    ],
    "NOTO": [
        {"id": "id3", "summary": "其他内容", "dialogs": ["user: 随便聊聊"]},
    ],
}


class TestRetrieveFullLlm:
    async def test_returns_matching_topics(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_full_llm(mock_chat, "天气怎么样", MEMOS_SAMPLE, 5)
        assert len(results) == 1
        topic, entry = results[0]
        assert topic == "天气"

    async def test_returns_empty_on_no_match(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "NOTO"
        results = await retrieve_full_llm(mock_chat, "无关查询", MEMOS_SAMPLE, 5)
        assert all(t == "NOTO" for t, _ in results) or len(results) == 0

    async def test_handles_multi_selection(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1#2"
        results = await retrieve_full_llm(mock_chat, "天气和会议", MEMOS_SAMPLE, 5)
        topics = {t for t, _ in results}
        assert len(topics) >= 1

    async def test_returns_empty_on_llm_error(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.side_effect = RuntimeError("fail")
        results = await retrieve_full_llm(mock_chat, "天气", MEMOS_SAMPLE, 5)
        assert results == []


class TestRetrieveHybrid:
    async def test_returns_results_with_embedding(
        self, mock_chat: MagicMock, mock_embedding: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_hybrid(
            mock_chat, mock_embedding, "天气", MEMOS_SAMPLE, 5
        )
        assert len(results) >= 1

    async def test_falls_back_to_keyword_without_embedding(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_hybrid(
            mock_chat, None, "天气", MEMOS_SAMPLE, 5
        )
        assert len(results) >= 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/stores/test_memochat_retriever.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 retriever 策略函数**

`app/memory/stores/memochat/retriever.py` 追加：
```python
"""MemoChat 检索策略."""

import logging
import re
from enum import StrEnum
from typing import Optional, TYPE_CHECKING

from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class RetrievalMode(StrEnum):
    """检索模式枚举."""

    FULL_LLM = "full_llm"
    HYBRID = "hybrid"


def _flatten_memos(
    memos: dict[str, list[dict]],
) -> list[tuple[str, dict]]:
    """展平 memos dict 为 (topic, entry) 元组列表."""
    results = []
    for topic, entries in memos.items():
        for entry in entries:
            results.append((topic, entry))
    return results


def _parse_selection(output: str, total: int) -> list[int]:
    """解析 LLM 输出为选中的索引列表."""
    indices = []
    for part in output.split("#"):
        part = part.strip()
        try:
            idx = int(re.sub(r"[^\d]", "", part))
            if 1 <= idx <= total:
                indices.append(idx - 1)
        except (ValueError, TypeError):
            continue
    return indices


async def retrieve_full_llm(
    chat_model: "ChatModel",
    query: str,
    memos: dict[str, list[dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    """全量 LLM 检索：将所有 memo 列给 LLM 选择."""
    from app.memory.stores.memochat.prompts import (
        RETRIEVAL_INSTRUCTION,
        RETRIEVAL_SYSTEM,
    )

    flat = _flatten_memos(memos)
    if not flat:
        return []
    options_text = "\n".join(
        f"({i + 1}) {topic}. {entry.get('summary', '')}"
        for i, (topic, entry) in enumerate(flat)
    )
    option_count = str(len(flat))
    system = RETRIEVAL_SYSTEM.replace("OPTION", option_count)
    task_case = (
        f"```\n查询语句：\n{query}\n主题选项：\n{options_text}\n```"
        + RETRIEVAL_INSTRUCTION.replace("OPTION", option_count)
    )
    prompt = system + task_case
    try:
        raw = await chat_model.generate(prompt)
    except Exception:
        logger.warning("Retrieval LLM call failed")
        return []
    selected_indices = _parse_selection(raw, len(flat))
    results = []
    for idx in selected_indices:
        if idx < len(flat):
            topic, entry = flat[idx]
            if topic != "NOTO":
                results.append((topic, entry))
    return results[:top_k]


async def retrieve_hybrid(
    chat_model: "ChatModel",
    embedding_model: Optional["EmbeddingModel"],
    query: str,
    memos: dict[str, list[dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    """混合检索：embedding/keyword 粗筛 + LLM 精筛."""
    flat = _flatten_memos(memos)
    if not flat:
        return []
    candidates = _coarse_filter(embedding_model, query, flat, top_k * 3)
    if not candidates:
        candidates = flat
    candidate_memos: dict[str, list[dict]] = {}
    for topic, entry in candidates:
        candidate_memos.setdefault(topic, []).append(entry)
    return await retrieve_full_llm(chat_model, query, candidate_memos, top_k)


def _coarse_filter(
    embedding_model: Optional["EmbeddingModel"],
    query: str,
    flat: list[tuple[str, dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    """粗筛候选."""
    if embedding_model is None:
        return _keyword_filter(query, flat, top_k)
    return _embedding_filter_sync(embedding_model, query, flat, top_k)


def _keyword_filter(
    query: str,
    flat: list[tuple[str, dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    query_lower = query.lower()
    scored = []
    for topic, entry in flat:
        text = f"{topic} {entry.get('summary', '')}".lower()
        if query_lower in text or any(c in text for c in query_lower):
            scored.append((topic, entry))
    return scored[:top_k]


def _embedding_filter_sync(
    embedding_model: "EmbeddingModel",
    query: str,
    flat: list[tuple[str, dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    import asyncio

    async def _async() -> list[tuple[str, dict]]:
        query_vec = await embedding_model.encode(query)
        texts = [
            f"{topic} {entry.get('summary', '')}" for topic, entry in flat
        ]
        if not texts:
            return []
        vectors = await embedding_model.batch_encode(texts)
        scored = []
        for (topic, entry), vec in zip(flat, vectors):
            sim = cosine_similarity(query_vec, vec)
            scored.append((sim, topic, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(t, e) for _, t, e in scored[:top_k]]

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, lambda: asyncio.run(_async()))  # type: ignore
    except RuntimeError:
        return asyncio.run(_async())
```

注意：`_embedding_filter_sync` 的异步处理在实际实现中需要更仔细地处理（因为在 async 上下文中无法直接 `asyncio.run`）。正式实现时应改为 `async def _embedding_filter` 并在 `retrieve_hybrid` 中 `await` 调用。上面是伪代码示意，实际实现应直接使用 async 版本。

- [ ] **Step 4: 运行测试验证**

Run: `uv run pytest tests/stores/test_memochat_retriever.py -v`

注意：测试中 `_embedding_filter_sync` 在 async 测试上下文会有问题，实际实现需将 `_coarse_filter` 改为 async 函数，`retrieve_hybrid` 中直接 await。

- [ ] **Step 5: 在 engine.py 中添加 `search` 和 `write_interaction` 方法**

在 `MemoChatEngine` 类中追加：

```python
    async def search(self, query: str, top_k: int = 10) -> list["SearchResult"]:
        from app.memory.schemas import SearchResult
        from app.memory.stores.memochat.retriever import retrieve_full_llm, retrieve_hybrid

        if not query.strip():
            return []
        memos = await self.read_memos()
        if not memos:
            return []
        if not self.chat_model:
            return []
        if self.retrieval_mode == RetrievalMode.HYBRID:
            matched = await retrieve_hybrid(
                self.chat_model, self.embedding_model, query, memos, top_k
            )
        else:
            matched = await retrieve_full_llm(self.chat_model, query, memos, top_k)
        return [
            SearchResult(
                event={
                    "id": entry.get("id", ""),
                    "content": f"{topic}: {entry.get('summary', '')}",
                    "description": " ### ".join(entry.get("dialogs", [])),
                },
                score=1.0,
                source="event",
            )
            for topic, entry in matched
        ]
```

- [ ] **Step 6: 运行全部 memochat 测试**

Run: `uv run pytest tests/stores/test_memochat_engine.py tests/stores/test_memochat_retriever.py -v`
Expected: PASS

- [ ] **Step 7: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 8: 提交**

```bash
git add app/memory/stores/memochat/ tests/stores/test_memochat_retriever.py tests/stores/test_memochat_engine.py
git commit -m "feat(memochat): implement retrieval stage with FULL_LLM and HYBRID modes"
```

---

### Task 4: MemoChatStore 实现 + 注册

**Files:**
- Create: `app/memory/stores/memochat/store.py`
- Modify: `app/memory/stores/memochat/__init__.py`
- Modify: `app/memory/types.py`
- Modify: `app/memory/memory.py`
- Create: `tests/stores/test_memochat_store.py`
- Modify: `tests/test_memory_types.py`

- [ ] **Step 1: 更新 `types.py` 测试**

`tests/test_memory_types.py`:
```python
"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat() -> None:
    assert MemoryMode.MEMORY_BANK == "memory_bank"
    assert MemoryMode.MEMORY_BANK in ["memory_bank"]


def test_memochat_str_enum_compat() -> None:
    assert MemoryMode.MEMOCHAT == "memochat"
    assert MemoryMode.MEMOCHAT in ["memochat"]


def test_all_values() -> None:
    assert set(MemoryMode) == {MemoryMode.MEMORY_BANK, MemoryMode.MEMOCHAT}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_memory_types.py -v`
Expected: FAIL

- [ ] **Step 3: 修改 `types.py`**

```python
class MemoryMode(StrEnum):
    """记忆检索模式."""

    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_memory_types.py -v`
Expected: PASS

- [ ] **Step 5: 写 MemoChatStore 测试**

`tests/stores/test_memochat_store.py`:
```python
"""MemoChatStore 测试."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.schemas import FeedbackData, MemoryEvent
from app.memory.stores.memochat.store import MemoChatStore


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock(return_value="测试摘要")
    return chat


@pytest.fixture
def store(tmp_path: Path, mock_chat: MagicMock) -> MemoChatStore:
    return MemoChatStore(tmp_path, chat_model=mock_chat)


class TestStoreAttributes:
    def test_store_name(self, store: MemoChatStore) -> None:
        assert store.store_name == "memochat"

    def test_requires_embedding_false(self, store: MemoChatStore) -> None:
        assert store.requires_embedding is False

    def test_requires_chat_true(self, store: MemoChatStore) -> None:
        assert store.requires_chat is True

    def test_supports_interaction_true(self, store: MemoChatStore) -> None:
        assert store.supports_interaction is True


class TestWrite:
    async def test_write_returns_string_id(self, store: MemoChatStore) -> None:
        event_id = await store.write(MemoryEvent(content="测试内容", type="测试主题"))
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    async def test_write_creates_memo_entry(self, store: MemoChatStore) -> None:
        await store.write(MemoryEvent(content="明天开会", type="会议"))
        memos = await store._engine.read_memos()
        assert "会议" in memos
        assert any("明天开会" in e.get("summary", "") for e in memos["会议"])


class TestGetHistory:
    async def test_get_history_returns_events(self, store: MemoChatStore) -> None:
        await store.write(MemoryEvent(content="事件1", type="主题1"))
        await store.write(MemoryEvent(content="事件2", type="主题2"))
        history = await store.get_history(limit=10)
        assert len(history) >= 2
        assert all(isinstance(e, MemoryEvent) for e in history)

    async def test_get_history_respects_limit(self, store: MemoChatStore) -> None:
        for i in range(5):
            await store.write(MemoryEvent(content=f"事件{i}", type=f"主题{i}"))
        history = await store.get_history(limit=3)
        assert len(history) == 3


class TestUpdateFeedback:
    async def test_update_feedback_records(self, store: MemoChatStore) -> None:
        event_id = await store.write(MemoryEvent(content="测试"))
        await store.update_feedback(
            event_id, FeedbackData(action="accept", type="meeting")
        )
        strategies = await store._feedback._strategies_store.read()
        assert "reminder_weights" in strategies
```

- [ ] **Step 6: 运行测试验证失败**

Run: `uv run pytest tests/stores/test_memochat_store.py -v`
Expected: FAIL

- [ ] **Step 7: 实现 `store.py`**

`app/memory/stores/memochat/store.py`:
```python
"""MemoChat 记忆存储后端."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from app.memory.components import EventStorage, FeedbackManager
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.stores.memochat.engine import MemoChatEngine
from app.memory.stores.memochat.retriever import RetrievalMode

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


class MemoChatStore:
    """MemoChat 记忆存储后端，基于三阶段 pipeline（summarization → retrieval → chat）."""

    store_name = "memochat"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
        retrieval_mode: RetrievalMode = RetrievalMode.FULL_LLM,
    ) -> None:
        self._storage = EventStorage(data_dir)
        self._engine = MemoChatEngine(
            data_dir, chat_model, embedding_model, retrieval_mode
        )
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    @property
    def events_store(self):
        return self._storage._store

    @property
    def strategies_store(self):
        return self._feedback._strategies_store

    async def write(self, event: MemoryEvent) -> str:
        memo_entry = {
            "id": self._storage.generate_id(),
            "summary": event.content,
            "dialogs": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "memory_strength": 1,
            "last_recall_date": datetime.now(timezone.utc).date().isoformat(),
        }
        topic = event.type or "general"
        memos = await self._engine.read_memos()
        memos.setdefault(topic, []).append(memo_entry)
        await self._engine._write_memos(memos)
        event_copy = event.model_copy(deep=True)
        event_copy.id = memo_entry["id"]
        event_copy.created_at = memo_entry["created_at"]
        await self._storage.append_raw(event_copy.model_dump())
        return memo_entry["id"]

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        return await self._engine.search(query, top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        memos = await self._engine.read_memos()
        all_entries = []
        for topic, entries in memos.items():
            for entry in entries:
                all_entries.append((topic, entry))
        all_entries.sort(
            key=lambda x: x[1].get("created_at", ""), reverse=True
        )
        results = []
        for topic, entry in all_entries[:limit]:
            results.append(
                MemoryEvent(
                    id=entry.get("id", ""),
                    content=f"{topic}: {entry.get('summary', '')}",
                    type="memochat_memo",
                    description=" ### ".join(entry.get("dialogs", [])),
                    memory_strength=entry.get("memory_strength", 1),
                    last_recall_date=entry.get("last_recall_date", ""),
                    date_group=entry.get("created_at", "")[:10],
                    created_at=entry.get("created_at", ""),
                )
            )
        return results

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        await self._feedback.update_feedback(event_id, feedback)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        from datetime import timezone as _tz

        now = datetime.now(_tz.utc)
        interaction_id = f"{now.strftime('%Y%m%d%H%M%S')}_{__import__('uuid').uuid4().hex[:8]}"
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": now.isoformat(),
        }
        await self._engine._interactions_store.append(interaction)
        await self._engine.append_recent_dialog(f"user: {query}")
        await self._engine.append_recent_dialog(f"bot: {response}")
        await self._engine._summarize_if_needed()
        return interaction_id
```

- [ ] **Step 8: 更新 `__init__.py`**

```python
"""MemoChat 记忆存储模块."""

from app.memory.stores.memochat.store import MemoChatStore

__all__ = ["MemoChatStore"]
```

- [ ] **Step 9: 注册到 `memory.py`**

在 `_import_all_stores()` 中追加：
```python
from app.memory.stores.memochat import MemoChatStore
register_store(MemoryMode.MEMOCHAT, MemoChatStore)
```

- [ ] **Step 10: 运行测试**

Run: `uv run pytest tests/stores/test_memochat_store.py tests/test_memory_types.py -v`
Expected: PASS

- [ ] **Step 11: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 12: 提交**

```bash
git add app/memory/stores/memochat/ app/memory/types.py app/memory/memory.py tests/
git commit -m "feat(memochat): implement MemoChatStore and register as MemoryMode.MEMOCHAT"
```

---

### Task 5: 契约测试集成

**Files:**
- Modify: `tests/test_memory_store_contract.py`

- [ ] **Step 1: 更新契约测试参数列表**

将 `_get_store_params()` 修改为：
```python
def _get_store_params() -> list[str]:
    return ["memory_bank", "memochat"]
```

注意：MemoChatStore 的 `search()` 依赖 LLM 调用（即使 FULL_LLM 模式）。契约测试 fixture 当前通过 `MemoryModule(tmp_path)` 创建 store，会触发 `get_chat_model()` 延迟初始化。需要修改 fixture 为 memochat 参数注入 mock chat model，或者用 `SKIP_IF_NO_LLM` 标记 memochat 的搜索相关测试。

推荐方案：修改 fixture，为 memochat 注入 mock_chat_model：

```python
@pytest.fixture(params=_get_store_params())
async def store(
    self, request: pytest.FixtureRequest, tmp_path: Path
) -> "MemoryStore":
    from app.memory.memory import MemoryModule
    from app.memory.types import MemoryMode
    from unittest.mock import MagicMock

    mode = MemoryMode(request.param)
    mm = MemoryModule(tmp_path)
    if mode == MemoryMode.MEMOCHAT:
        mock_chat = MagicMock()
        mock_chat.generate = AsyncMock(return_value="无相关主题")
        mm._chat_model = mock_chat
    return await mm._get_store(mode)
```

同时需要在文件顶部添加 `from unittest.mock import AsyncMock`。

- [ ] **Step 2: 运行契约测试**

Run: `uv run pytest tests/test_memory_store_contract.py -v`
Expected: PASS（两个后端都通过所有契约测试）

- [ ] **Step 3: 运行完整测试套件**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 5: 提交**

```bash
git add tests/test_memory_store_contract.py
git commit -m "test(memochat): add MemoChatStore to MemoryStore contract tests"
```

---

### Task 6: write_interaction 与 PersonalityManager 集成

**Files:**
- Modify: `app/memory/stores/memochat/engine.py`
- Modify: `app/memory/stores/memochat/store.py`
- Modify: `tests/stores/test_memochat_store.py`

- [ ] **Step 1: 写集成测试**

在 `tests/stores/test_memochat_store.py` 追加：
```python
class TestWriteInteractionPersonality:
    async def test_interaction_stored(
        self, store: MemoChatStore
    ) -> None:
        iid = await store.write_interaction("提醒我开会", "好的已记录")
        interactions = await store._engine.read_interactions()
        assert any(i["id"] == iid for i in interactions)

    async def test_interaction_has_event_id_after_summary(
        self, store: MemoChatStore, mock_chat: MagicMock
    ) -> None:
        import json
        mock_chat.generate.return_value = json.dumps([
            {"topic": "会议", "summary": "用户有会议安排", "start": 1, "end": 2}
        ])
        from app.memory.stores.memochat.engine import SUMMARIZATION_TURN_THRESHOLD
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await store.write_interaction(f"第{i}条消息", f"回复{i}")
        interactions = await store._engine.read_interactions()
        has_event_id = any(i.get("event_id") for i in interactions)
        assert has_event_id
```

- [ ] **Step 2: 实现回填逻辑**

在 `engine.py` 的 `_summarize_if_needed` 中，写入 memos 后，回溯更新 interactions 的 `event_id`：

```python
        async with self._lock:
            await self._write_memos(memos)
            interactions = await self._interactions_store.read()
            if interactions and parsed:
                last_memo_id = None
                for topic_entries in memos.values():
                    for e in topic_entries:
                        if e.get("id"):
                            last_memo_id = e["id"]
                if last_memo_id:
                    for interaction in interactions:
                        if not interaction.get("event_id"):
                            interaction["event_id"] = last_memo_id
                    await self._interactions_store.write(interactions)
            truncated = dialogs[-RECENT_DIALOGS_KEEP_AFTER_SUMMARY:]
            await self._dialogs_store.write(truncated)
```

- [ ] **Step 3: 在 `store.py` 的 `write_interaction` 中调用 PersonalityManager**

```python
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        ...（现有逻辑）
        # 触发人格分析
        from app.memory.stores.memory_bank.personality import PersonalityManager
        events = await self._storage.read_events()
        interactions_raw = await self._engine.read_interactions()
        today = datetime.now(timezone.utc).date().isoformat()
        pm = PersonalityManager(self._engine.data_dir)
        await pm.maybe_summarize(today, events, interactions_raw, self.chat_model)
        return interaction_id
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/stores/test_memochat_store.py -v`
Expected: PASS

- [ ] **Step 5: 运行完整测试套件**

Run: `uv run pytest tests/ -v`

- [ ] **Step 6: Lint + 类型检查**

Run: `uv run ruff check --fix && uv run ty check && uv run ruff format`

- [ ] **Step 7: 提交**

```bash
git add app/memory/stores/memochat/ tests/stores/test_memochat_store.py
git commit -m "feat(memochat): integrate PersonalityManager with event_id backfill"
```

---

## 未解决问题

1. **`_create_store()` 的 `retrieval_mode` 传递**：当前工厂不透传额外 kwargs。需要决定是通过环境变量、配置文件、还是修改工厂方法签名。建议在 Task 4 中同步处理。
2. **Embedding 异步上下文**：`retriever.py` 中 `_embedding_filter` 需要是真正的 async 函数，不能在已有 event loop 中 `asyncio.run()`。Task 3 实现时需注意。
3. **Benchmark adapter**：MemoChat 后端的 VehicleMemBench 适配器未在此计划中，需单独任务。
