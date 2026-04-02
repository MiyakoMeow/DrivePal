"""MemoChatEngine — 摘要阶段引擎."""

import asyncio
import contextlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from random import sample
from typing import TYPE_CHECKING, Optional

from app.memory.stores.memochat.prompts import WRITING_INSTRUCTION, WRITING_SYSTEM
from app.memory.stores.memochat.retriever import RetrievalMode
from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from app.memory.schemas import SearchResult
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

MAX_LEN = 2048
TARGET_LEN = 512
SUMMARIZATION_CHAR_THRESHOLD = MAX_LEN // 2
SUMMARIZATION_TURN_THRESHOLD = 10
RECENT_DIALOGS_KEEP_AFTER_SUMMARY = 2

_DEFAULT_GREETINGS = ["user: 你好！", "bot: 你好！我是你的行车助手。"]


def _normalize_model_outputs(model_text: str) -> list[dict]:
    extracted_elements = [
        re.sub(r"\s+", " ", mt.replace('"', "").replace("'", ""))
        for mt in re.findall(r"'[^']*'|\"[^\"]*\"|\d+", model_text)
    ]
    outputs: list[dict] = []
    ti = 0
    while ti + 7 < len(extracted_elements):
        if (
            extracted_elements[ti] == "topic"
            and extracted_elements[ti + 2] == "summary"
            and extracted_elements[ti + 4] == "start"
            and extracted_elements[ti + 6] == "end"
        ):
            with contextlib.suppress(ValueError, IndexError):
                outputs.append(
                    {
                        "topic": extracted_elements[ti + 1],
                        "summary": extracted_elements[ti + 3],
                        "start": int(extracted_elements[ti + 5]),
                        "end": int(extracted_elements[ti + 7]),
                    }
                )
        ti += 1
    return outputs


def _parse_json_outputs(text: str) -> list[dict]:
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return _normalize_model_outputs(text)


class MemoChatEngine:
    """MemoChat 摘要引擎，管理对话摘要与记忆写入."""

    store_name = "memochat"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        chat: Optional["ChatModel"],
        embedding: Optional["EmbeddingModel"],
        retrieval_mode: RetrievalMode,
    ) -> None:
        """初始化 MemoChatEngine."""
        self.data_dir = data_dir
        self.chat = chat
        self.embedding = embedding
        self.retrieval_mode = retrieval_mode

        self._dialogs_store = TOMLStore(
            data_dir, Path("memochat_recent_dialogs.toml"), list
        )
        self._memos_store = TOMLStore(data_dir, Path("memochat_memos.toml"), dict)
        self._interactions_store = TOMLStore(
            data_dir, Path("memochat_interactions.toml"), list
        )
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            dialogs = await self._dialogs_store.read()
            if not dialogs:
                await self._dialogs_store.write(list(_DEFAULT_GREETINGS))
            memos = await self._memos_store.read()
            if "NOTO" not in memos:
                memos["NOTO"] = [{"summary": "以上皆不相关。", "dialogs": []}]
                await self._memos_store.write(memos)
            self._initialized = True

    async def read_recent_dialogs(self) -> list[str]:
        """读取近期对话列表."""
        await self._ensure_initialized()
        return await self._dialogs_store.read()

    async def append_recent_dialog(self, dialog: str) -> None:
        """追加一条对话到近期对话列表."""
        await self._ensure_initialized()
        await self._dialogs_store.append(dialog)

    async def read_memos(self) -> dict:
        """读取全部记忆条目."""
        await self._ensure_initialized()
        return await self._memos_store.read()

    async def _write_memos(self, memos: dict) -> None:
        await self._memos_store.write(memos)

    def _should_summarize(self, dialogs: list[str]) -> bool:
        if len(dialogs) >= SUMMARIZATION_TURN_THRESHOLD:
            return True
        total_chars = sum(len(d) for d in dialogs)
        return total_chars > SUMMARIZATION_CHAR_THRESHOLD

    def _generate_id(self) -> str:
        return f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    async def _summarize_if_needed(self) -> None:
        dialogs = await self.read_recent_dialogs()
        if not self._should_summarize(dialogs):
            return
        if self.chat is None:
            return

        conversation_lines = dialogs
        history_log = "\n".join(
            f"(line {i + 1}) {d}" for i, d in enumerate(conversation_lines)
        )
        line_count = len(conversation_lines)
        system = WRITING_SYSTEM.replace("LINE", str(line_count))
        instruction = WRITING_INSTRUCTION.replace("LINE", str(line_count))

        prompt = (
            system + "\n\n```\n任务对话：\n" + history_log + "\n```\n" + instruction
        )

        try:
            raw_output = await self.chat.generate(prompt)
        except Exception:
            return

        parsed = _parse_json_outputs(raw_output)
        memos = await self.read_memos()

        if parsed:
            for entry in parsed:
                topic = entry.get("topic", "NOTO")
                start = max(1, entry.get("start", 1)) - 1
                end = entry.get("end", start + 1)
                related = conversation_lines[start:end]
                memo_item = {
                    "id": self._generate_id(),
                    "summary": entry.get("summary", ""),
                    "dialogs": related,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "memory_strength": 1,
                    "last_recall_date": datetime.now(timezone.utc).isoformat(),
                }
                if topic not in memos:
                    memos[topic] = []
                memos[topic].append(memo_item)
        else:
            n_dialogs = len(conversation_lines)
            sample_count = min(2, n_dialogs)
            sampled = sample(conversation_lines, sample_count)
            noto_entry = {
                "id": self._generate_id(),
                "summary": f"Partial dialogs about: {' or '.join(sampled)}.",
                "dialogs": conversation_lines,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "memory_strength": 1,
                "last_recall_date": datetime.now(timezone.utc).isoformat(),
            }
            if "NOTO" not in memos:
                memos["NOTO"] = []
            memos["NOTO"].append(noto_entry)

        await self._write_memos(memos)

        kept = dialogs[-RECENT_DIALOGS_KEEP_AFTER_SUMMARY:]
        await self._dialogs_store.write(kept)

    async def search(self, query: str, top_k: int = 10) -> list["SearchResult"]:
        """检索与查询相关的记忆条目."""
        from app.memory.schemas import SearchResult
        from app.memory.stores.memochat.retriever import (
            retrieve_full_llm,
            retrieve_hybrid,
        )

        if not query.strip():
            return []
        memos = await self.read_memos()
        if not memos:
            return []
        if not self.chat:
            return []
        if self.retrieval_mode == RetrievalMode.HYBRID:
            matched = await retrieve_hybrid(
                self.chat, self.embedding, query, memos, top_k
            )
        else:
            matched = await retrieve_full_llm(self.chat, query, memos, top_k)
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
