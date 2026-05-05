"""四阶段检索管道。

从 VehicleMemBench memorybank.py 移植并适配：
- 阶段 1: query embedding + FAISS 粗排
- 阶段 2: 邻居合并（同 source 连续条目）
- 阶段 3: 重叠去重（并查集）
- 阶段 4: 说话人感知降权
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.memory.stores.memory_bank.faiss_index import FaissIndex
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

COARSE_SEARCH_FACTOR = 4
_MERGED_TEXT_DELIMITER = "\x00"
DEFAULT_CHUNK_SIZE = 1500
CHUNK_SIZE_MIN = 200
CHUNK_SIZE_MAX = 8192
INITIAL_MEMORY_STRENGTH = 1
_INTERNAL_KEYS: frozenset[str] = frozenset(
    {
        "_merged_indices",
        "_all_meta_indices",
        "_meta_idx",
        "faiss_id",
    }
)


def _resolve_chunk_size() -> int:
    raw = os.getenv("MEMORYBANK_CHUNK_SIZE")
    if raw is not None:
        try:
            return max(CHUNK_SIZE_MIN, min(CHUNK_SIZE_MAX, int(raw)))
        except ValueError:
            pass
    return DEFAULT_CHUNK_SIZE


def _safe_memory_strength(value: Any) -> float:  # noqa: ANN401
    try:
        f = float(value)
    except TypeError, ValueError:
        logger.warning(
            "memory_strength=%r 无效（非数字），回退至 %d",
            value,
            INITIAL_MEMORY_STRENGTH,
        )
        return float(INITIAL_MEMORY_STRENGTH)
    if math.isnan(f) or math.isinf(f) or f <= 0:
        logger.warning(
            "memory_strength=%r 无效（NaN/Inf/非正），回退至 %d",
            value,
            INITIAL_MEMORY_STRENGTH,
        )
        return float(INITIAL_MEMORY_STRENGTH)
    return f


def _strip_source_prefix(text: str, date_part: str) -> str:
    for pfx in (
        f"Conversation content on {date_part}:",
        f"The summary of the conversation on {date_part} is:",
    ):
        if text.startswith(pfx):
            return text[len(pfx) :]
    return text


def _merge_overlapping_results(results: list[dict]) -> list[dict]:  # noqa: C901, PLR0912
    non_merging = [
        r
        for r in results
        if not isinstance(r.get("_merged_indices"), list)
        or len(r["_merged_indices"]) <= 1
    ]
    merging = [
        r
        for r in results
        if isinstance(r.get("_merged_indices"), list) and len(r["_merged_indices"]) > 1
    ]
    if len(merging) <= 1:
        return results

    idx_owners: dict[int, list[int]] = defaultdict(list)
    for ri, r in enumerate(merging):
        for idx in r["_merged_indices"]:
            idx_owners[idx].append(ri)

    parent = {i: i for i in range(len(merging))}

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        px, py = _find(x), _find(y)
        if px != py:
            parent[py] = px

    for owners in idx_owners.values():
        for i in range(1, len(owners)):
            _union(owners[0], owners[i])

    groups = defaultdict(list)
    for i in range(len(merging)):
        groups[_find(i)].append(i)

    merged: list[dict] = []
    for members in groups.values():
        if len(members) == 1:
            merged.append(merging[members[0]])
        else:
            all_indices: set[int] = set()
            best_idx = max(members, key=lambda mi: merging[mi].get("score", 0.0))
            for mi in members:
                all_indices.update(merging[mi]["_merged_indices"])
            r = dict(merging[best_idx])
            r["_merged_indices"] = sorted(all_indices)
            r["_all_meta_indices"] = sorted(
                {
                    merging[mi].get("_meta_idx")
                    for mi in members
                    if merging[mi].get("_meta_idx") is not None
                }
            )
            r["memory_strength"] = max(
                _safe_memory_strength(
                    merging[mi].get("memory_strength", INITIAL_MEMORY_STRENGTH)
                )
                for mi in members
            )
            r["speakers"] = sorted(
                {s for mi in members for s in (merging[mi].get("speakers") or [])}
            )
            index_to_part: dict[int, str] = {}
            for mi in members:
                parts = merging[mi].get("text", "").split(_MERGED_TEXT_DELIMITER)
                indices = merging[mi].get("_merged_indices", [])
                if len(indices) != len(parts):
                    logger.warning(
                        "_merge_overlapping_results text/indices "
                        "长度不匹配 (%d vs %d) for result %d，跳过",
                        len(indices),
                        len(parts),
                        mi,
                    )
                    continue
                for idx, part in zip(indices, parts, strict=True):
                    index_to_part.setdefault(idx, part)
            deduped_parts = [
                index_to_part[idx]
                for idx in r["_merged_indices"]
                if idx in index_to_part
            ]
            if deduped_parts:
                r["text"] = _MERGED_TEXT_DELIMITER.join(deduped_parts)
            else:
                if not r.get("text", ""):
                    r["text"] = next(iter(index_to_part.values()), "")
                if not r.get("text", ""):
                    logger.warning(
                        "_merge_overlapping_results 合并结果为空文本 "
                        "(best_idx=%s, _meta_idx=%s, "
                        "%d members, %d parts recovered)。"
                        "元数据损坏 — 跳过此结果。",
                        best_idx,
                        merging[best_idx].get("_meta_idx"),
                        len(members),
                        len(index_to_part),
                    )
                    continue
            merged.append(r)

    if non_merging:
        merged.extend(non_merging)
    merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    return merged


def _clean_search_result(result: dict) -> None:
    for key in _INTERNAL_KEYS:
        result.pop(key, None)
    text = result.get("text")
    if text:
        result["text"] = text.replace(_MERGED_TEXT_DELIMITER, "; ")


def _word_in_text(word: str, text: str) -> bool:
    if not word or not word.strip():
        return False
    return bool(re.search(r"\b" + re.escape(word.strip()) + r"\b", text))


class RetrievalPipeline:
    """四阶段检索管道。

    阶段 1: query embedding + FAISS 粗排
    阶段 2: 邻居合并（同 source 连续条目）
    阶段 3: 重叠去重（并查集）
    阶段 4: 说话人感知降权
    """

    def __init__(self, index: FaissIndex, embedding_model: EmbeddingModel) -> None:  # noqa: D107
        self._index = index
        self._embedding_model = embedding_model
        self._chunk_size = _resolve_chunk_size()

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """执行四阶段检索管道。"""
        query_emb = await self._embedding_model.encode(query)
        index_total = self._index.total
        if index_total == 0:
            return []
        coarse_k = min(top_k * COARSE_SEARCH_FACTOR, index_total)
        results = await self._index.search(query_emb, coarse_k)
        if not results:
            return []
        # 过滤已遗忘条目（maybe_forget 在 store.py 中已设 forgotten 标记）
        results = [r for r in results if not r.get("forgotten")]
        if not results:
            return []

        metadata = self._index.get_metadata()
        merged = self._merge_neighbors(results, metadata)
        # 注意：_merge_neighbors 内部已调用 _merge_overlapping_results，
        # 此处不再重复调用。

        merged = self._apply_speaker_filter(merged, query)

        merged = merged[:top_k]

        for r in merged:
            all_mi: list[int] = []
            ai = r.get("_all_meta_indices")
            if isinstance(ai, list):
                all_mi.extend(ai)
            else:
                mi = r.get("_meta_idx")
                if mi is not None:
                    all_mi.append(mi)
            for mi in all_mi:
                if 0 <= mi < len(metadata):
                    old = float(
                        metadata[mi].get("memory_strength", INITIAL_MEMORY_STRENGTH)
                    )
                    metadata[mi]["memory_strength"] = old + 1.0

        for r in merged:
            _clean_search_result(r)
        await self._index.save()
        return merged

    def _merge_neighbors(self, results: list[dict], metadata: list[dict]) -> list[dict]:  # noqa: C901, PLR0912, PLR0915
        if not results:
            return results

        if not metadata:
            return results

        indexed = [
            (r, r["_meta_idx"]) for r in results if r.get("_meta_idx") is not None
        ]
        if not indexed:
            return results
        non_indexed = [r for r in results if r.get("_meta_idx") is None]

        merged_results: list[dict] = []

        for r, meta_idx in indexed:
            score = float(r.get("score", 0.0))
            source = r.get("source", "")

            neighbor_indices: list[int] = [meta_idx]

            pos = meta_idx + 1
            while pos < len(metadata) and metadata[pos].get("source") == source:
                if not metadata[pos].get("forgotten"):
                    neighbor_indices.append(pos)
                pos += 1

            pos = meta_idx - 1
            while pos >= 0 and metadata[pos].get("source") == source:
                if not metadata[pos].get("forgotten"):
                    neighbor_indices.append(pos)
                pos -= 1

            neighbor_indices.sort()
            # 确保原始命中点始终在候选列表中（可能已被跳过）
            if meta_idx not in neighbor_indices:
                neighbor_indices.insert(0, meta_idx)

            trim_queue = deque(neighbor_indices)
            total = sum(len(metadata[i].get("text", "")) for i in trim_queue)
            while len(trim_queue) > 1:
                if total <= self._chunk_size:
                    break
                left_dist = meta_idx - trim_queue[0]
                right_dist = trim_queue[-1] - meta_idx
                if left_dist >= right_dist:
                    removed = trim_queue.popleft()
                else:
                    removed = trim_queue.pop()
                total -= len(metadata[removed].get("text", ""))
            neighbor_indices = list(trim_queue)

            parts: list[str] = []
            for idx in neighbor_indices:
                t = metadata[idx].get("text", "")
                src = metadata[idx].get("source", "")
                date_part = src.removeprefix("summary_")
                t = _strip_source_prefix(t, date_part)
                parts.append(t.strip())

            combined_text = _MERGED_TEXT_DELIMITER.join(parts)
            base_meta = dict(metadata[neighbor_indices[0]])
            base_meta["text"] = combined_text
            base_meta["_meta_idx"] = meta_idx

            base_meta["score"] = float(score)

            if len(neighbor_indices) > 1:
                base_meta["_merged_indices"] = sorted(neighbor_indices)
                base_meta["speakers"] = sorted(
                    {
                        s
                        for i in neighbor_indices
                        for s in (metadata[i].get("speakers") or [])
                    }
                )
                base_meta["memory_strength"] = max(
                    _safe_memory_strength(
                        metadata[i].get("memory_strength", INITIAL_MEMORY_STRENGTH)
                    )
                    for i in neighbor_indices
                )
            merged_results.append(base_meta)

        if len(merged_results) > 1:
            merged_results = _merge_overlapping_results(merged_results)

        merged_results.extend(non_indexed)
        merged_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return merged_results

    def _apply_speaker_filter(self, results: list[dict], query: str) -> list[dict]:
        ql = query.lower()
        speakers_in_query = {
            s for r in results for s in (r.get("speakers") or []) if s.lower() in ql
        }
        if not speakers_in_query:
            return results
        for r in results:
            rs = {s.lower() for s in (r.get("speakers") or [])}
            if not rs.intersection(speakers_in_query):
                r["score"] = r.get("score", 0.0) * 0.75
        return results
