"""MemoChat 检索策略."""

import logging
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class RetrievalMode(StrEnum):
    """检索模式枚举."""

    FULL_LLM = "full_llm"
    HYBRID = "hybrid"


def _flatten_memos(memos: dict[str, list[dict]]) -> list[tuple[str, dict]]:
    return [(topic, entry) for topic, entries in memos.items() for entry in entries]


def _parse_selection(output: str, total: int) -> list[int]:
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
    """基于 LLM 的全量检索策略."""
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
    """混合检索策略：先粗筛再 LLM 精排."""
    flat = _flatten_memos(memos)
    if not flat:
        return []
    candidates = await _coarse_filter(embedding_model, query, flat, top_k * 3)
    if not candidates:
        candidates = flat
    candidate_memos: dict[str, list[dict]] = {}
    for topic, entry in candidates:
        candidate_memos.setdefault(topic, []).append(entry)
    return await retrieve_full_llm(chat_model, query, candidate_memos, top_k)


async def _coarse_filter(
    embedding_model: Optional["EmbeddingModel"],
    query: str,
    flat: list[tuple[str, dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    if embedding_model is None:
        return _keyword_filter(query, flat, top_k)
    return await _embedding_filter(embedding_model, query, flat, top_k)


def _keyword_filter(
    query: str, flat: list[tuple[str, dict]], top_k: int
) -> list[tuple[str, dict]]:
    query_lower = query.lower()
    scored = []
    for topic, entry in flat:
        text = f"{topic} {entry.get('summary', '')}".lower()
        if query_lower in text or any(c in text for c in query_lower):
            scored.append((topic, entry))
    return scored[:top_k]


async def _embedding_filter(
    embedding_model: "EmbeddingModel",
    query: str,
    flat: list[tuple[str, dict]],
    top_k: int,
) -> list[tuple[str, dict]]:
    query_vec = await embedding_model.encode(query)
    texts = [f"{topic} {entry.get('summary', '')}" for topic, entry in flat]
    if not texts:
        return []
    vectors = await embedding_model.batch_encode(texts)
    scored = []
    for (topic, entry), vec in zip(flat, vectors):
        sim = cosine_similarity(query_vec, vec)
        scored.append((sim, topic, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(t, e) for _, t, e in scored[:top_k]]
