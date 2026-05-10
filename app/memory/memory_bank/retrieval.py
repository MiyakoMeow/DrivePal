"""四阶段检索管道。

从 VehicleMemBench memorybank.py 移植并适配：
- 阶段 1: query embedding + FAISS 粗排
- 阶段 2: 邻居合并（同 source 连续条目）
- 阶段 3: 重叠去重（并查集）
- 阶段 4: 说话人感知降权
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from app.memory.embedding_client import EmbeddingClient

    from .config import MemoryBankConfig
    from .index_reader import IndexReader

logger = logging.getLogger(__name__)

_MERGED_TEXT_DELIMITER = "\x00"
_ADAPTIVE_CHUNK_MIN_ENTRIES = 10
INITIAL_MEMORY_STRENGTH = 1
_INTERNAL_KEYS: frozenset[str] = frozenset(
    {
        "_merged_indices",
        "_all_meta_indices",
        "_meta_idx",
        "faiss_id",
    }
)


def _get_effective_chunk_size(
    metadata: list[dict],
    config: MemoryBankConfig,
) -> int:
    """基于 metadata 中文本长度的 P90 ×3 动态校准 chunk_size。

    config.chunk_size 显式设置时直接使用该值。
    metadata 不足 10 条时回退 DEFAULT_CHUNK_SIZE。
    """
    if config.chunk_size is not None:
        return max(config.chunk_size_min, min(config.chunk_size_max, config.chunk_size))
    lengths = sorted(len(m.get("text", "")) for m in metadata)
    if len(lengths) < _ADAPTIVE_CHUNK_MIN_ENTRIES:
        return config.default_chunk_size
    p90_idx = math.ceil(len(lengths) * 0.9) - 1
    p90 = lengths[p90_idx]
    return max(config.chunk_size_min, min(config.chunk_size_max, p90 * 3))


def _safe_memory_strength(value: object) -> float:
    try:
        f = float(cast("Any", value))
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


def _build_overlap_groups(merging: list[dict]) -> dict[int, list[int]]:
    """用并查集将重叠结果分组为连通分量。"""
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

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(merging)):
        groups[_find(i)].append(i)
    return groups


def _merge_result_group(merging: list[dict], members: list[int]) -> dict | None:
    """合并单个分组（一组重叠结果 → 一条结果）。"""
    if len(members) == 1:
        return merging[members[0]]

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
                "text/indices 长度不匹配 (%d vs %d) for result %d，跳过",
                len(indices),
                len(parts),
                mi,
            )
            continue
        for idx, part in zip(indices, parts, strict=True):
            index_to_part.setdefault(idx, part)

    deduped_parts = [
        index_to_part[idx] for idx in r["_merged_indices"] if idx in index_to_part
    ]
    if deduped_parts:
        r["text"] = _MERGED_TEXT_DELIMITER.join(deduped_parts)
    else:
        if not r.get("text", ""):
            r["text"] = next(iter(index_to_part.values()), "")
        if not r.get("text", ""):
            logger.warning(
                "合并结果为空文本 (best_idx=%s, %d members, %d parts)。"
                "元数据损坏 — 跳过。",
                best_idx,
                len(members),
                len(index_to_part),
            )
            return None
    return r


def _merge_overlapping_results(results: list[dict]) -> list[dict]:
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

    groups = _build_overlap_groups(merging)

    merged: list[dict] = []
    for members in groups.values():
        r = _merge_result_group(merging, members)
        if r is not None:
            merged.append(r)

    if non_merging:
        merged.extend(non_merging)
    merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    return merged


def _update_memory_strengths(
    results: list[dict],
    metadata: list[dict],
    config: MemoryBankConfig,
    reference_date: str | None = None,
) -> bool:
    """更新命中条目的记忆强度，返回是否有修改。

    记忆强度受 max_memory_strength 上限约束，防止无限回忆强化。
    """
    updated = False
    for r in results:
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
                new_strength = min(
                    _safe_memory_strength(
                        metadata[mi].get("memory_strength", INITIAL_MEMORY_STRENGTH)
                    )
                    + 1.0,
                    float(config.max_memory_strength),
                )
                metadata[mi]["memory_strength"] = new_strength
                today = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
                if metadata[mi].get("last_recall_date") != today:
                    metadata[mi]["last_recall_date"] = today
                updated = True
    return updated


def _gather_neighbor_indices(
    metadata: list[dict], meta_idx: int, source: str
) -> list[int]:
    """收集同 source 的邻居索引（包含原始命中点）。"""
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
    return neighbor_indices


def _trim_to_chunk_size(
    neighbor_indices: list[int],
    metadata: list[dict],
    meta_idx: int,
    max_chars: int,
) -> list[int]:
    """从两端裁剪邻居列表，使总文本不超过 max_chars。"""
    queue = deque(neighbor_indices)
    total = sum(len(metadata[i].get("text", "")) for i in queue)
    while len(queue) > 1 and total > max_chars:
        left_dist = meta_idx - queue[0]
        right_dist = queue[-1] - meta_idx
        removed = queue.popleft() if left_dist >= right_dist else queue.pop()
        total -= len(metadata[removed].get("text", ""))
    return list(queue)


def _build_neighbor_result(
    neighbor_indices: list[int],
    metadata: list[dict],
    meta_idx: int,
    score: float,
) -> dict:
    """构建合并后的邻居结果字典。"""
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
    base_meta["score"] = score

    if len(neighbor_indices) > 1:
        base_meta["_merged_indices"] = sorted(neighbor_indices)
        base_meta["speakers"] = sorted(
            {s for i in neighbor_indices for s in (metadata[i].get("speakers") or [])}
        )
        base_meta["memory_strength"] = max(
            _safe_memory_strength(
                metadata[i].get("memory_strength", INITIAL_MEMORY_STRENGTH)
            )
            for i in neighbor_indices
        )
    return base_meta


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

    _apply_speaker_filter 通过遍历结果条目中的 speakers 字段工作，
    不依赖 FaissIndex.get_all_speakers()，迁移 IndexReader 后行为不变。
    """

    def __init__(
        self,
        index: IndexReader,
        embedding_client: EmbeddingClient,
        config: MemoryBankConfig,
    ) -> None:
        """初始化检索管道。"""
        self._index = index
        self._embedding_client = embedding_client
        self._config = config
        self._bm25_corpus: list[str] = []
        self._bm25_meta_indices: list[int] = []
        self._bm25_index: Any = None
        self._bm25_lock = asyncio.Lock()

    async def search(
        self, query: str, top_k: int = 5, reference_date: str | None = None
    ) -> tuple[list[dict], bool]:
        """执行四阶段检索管道。

        Returns:
            (results, updated): results 是检索结果列表，updated 指示是否有
            memory_strength 变更（调用方应在合适时机持久化索引）。

        """
        if top_k <= 0:
            return [], False
        query_emb = await self._embedding_client.encode(query)
        index_total = self._index.total
        if index_total == 0:
            return [], False
        coarse_factor = self._config.coarse_search_factor
        if coarse_factor <= 0:
            coarse_factor = 4
        coarse_k = min(top_k * coarse_factor, index_total)
        results = await self._index.search(query_emb, coarse_k)
        if not results:
            return [], False

        metadata = self._index.get_metadata()

        results = await self._apply_bm25_fallback(results, query, metadata, coarse_k)

        # 过滤已遗忘条目（maybe_forget 在 store.py/lifecycle.py 中已设 forgotten 标记）
        results = [r for r in results if not r.get("forgotten")]
        # 过滤低于相似度阈值的条目（低分不配获得邻居扩展）
        results = [
            r
            for r in results
            if float(r.get("score", 0.0)) >= self._config.embedding_min_similarity
        ]
        if not results:
            return [], False

        merged = self._merge_neighbors(results, metadata)
        # 注意：_merge_neighbors 内部已调用 _merge_overlapping_results，
        # 此处不再重复调用。

        merged = self._apply_speaker_filter(merged, query)
        merged = self._apply_retention_weighting(merged, metadata, reference_date)
        merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        merged = merged[:top_k]

        updated = _update_memory_strengths(
            merged, metadata, self._config, reference_date=reference_date
        )
        for r in merged:
            _clean_search_result(r)
        return merged, updated

    async def _apply_bm25_fallback(
        self,
        results: list[dict],
        query: str,
        metadata: list[dict],
        coarse_k: int,
    ) -> list[dict]:
        """BM25 稀疏检索回退：FAISS 密集检索失效时的兜底。

        当 FAISS 最高分低于阈值时，重建 BM25 索引并补充检索结果。
        """
        if not self._config.bm25_fallback_enabled:
            return results
        max_faiss_score = max(float(r.get("score", 0.0)) for r in results)
        if max_faiss_score >= self._config.bm25_fallback_threshold:
            return results
        if self._bm25_index is None:
            async with self._bm25_lock:
                if self._bm25_index is None:
                    self._rebuild_bm25_index()
        if self._bm25_index is None:
            return results
        tokenized_query = query.lower().split()
        bm25_scores = self._bm25_index.get_scores(tokenized_query)
        max_bm25 = max(bm25_scores) if len(bm25_scores) > 0 else 1.0
        if max_bm25 > 0:
            bm25_scores = [s / max_bm25 for s in bm25_scores]
        top_indices = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:coarse_k]
        for idx in top_indices:
            meta_idx = self._bm25_meta_indices[idx]
            meta = metadata[meta_idx]
            results.append(
                {
                    "faiss_id": meta.get("faiss_id"),
                    "text": meta.get("text", ""),
                    "source": meta.get("source", ""),
                    "score": float(bm25_scores[idx]),
                    "_meta_idx": meta_idx,
                    "speakers": meta.get("speakers", []),
                    "memory_strength": meta.get(
                        "memory_strength", INITIAL_MEMORY_STRENGTH
                    ),
                    "forgotten": meta.get("forgotten", False),
                }
            )
        return results

    def _merge_neighbors(self, results: list[dict], metadata: list[dict]) -> list[dict]:
        if not results or not metadata:
            return results

        effective_chunk = _get_effective_chunk_size(metadata, self._config)
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

            neighbors = _gather_neighbor_indices(metadata, meta_idx, source)
            neighbors = _trim_to_chunk_size(
                neighbors, metadata, meta_idx, effective_chunk
            )
            merged_results.append(
                _build_neighbor_result(neighbors, metadata, meta_idx, score)
            )

        if len(merged_results) > 1:
            merged_results = _merge_overlapping_results(merged_results)

        merged_results.extend(non_indexed)
        merged_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return merged_results

    def _apply_speaker_filter(self, results: list[dict], query: str) -> list[dict]:
        ql = query.lower()
        speakers_in_query: set[str] = set()
        for r in results:
            for spk in r.get("speakers") or []:
                spk_lower = spk.lower()
                first = spk.split(" ", 1)[0].lower()
                if _word_in_text(spk_lower, ql) or _word_in_text(first, ql):
                    speakers_in_query.add(spk_lower)
        if not speakers_in_query:
            return results
        for r in results:
            rs = {s.lower() for s in (r.get("speakers") or [])}
            if not rs.intersection(speakers_in_query):
                score = r.get("score", 0.0)
                # 说话人不匹配降权 25%：正分压低，负分推低（降序排列更靠后）。
                # 0.75/1.25 为经验值，与原始 MemoryBank 论文一致。
                r["score"] = score * 0.75 if score >= 0 else score * 1.25
        return results

    def _apply_retention_weighting(
        self,
        results: list[dict],
        metadata: list[dict],
        reference_date: str | None = None,
    ) -> list[dict]:
        """对检索结果应用 Ebbinghaus 保留率加权。

        公式: adjusted = α × max(score, 0.0) + (1-α) × retention
        其中 retention = e^(-days / (time_scale × strength))
        """
        alpha = self._config.retrieval_alpha
        ref = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            ref_date = date.fromisoformat(ref)
        except ValueError:
            ref_date = datetime.now(UTC).date()

        for r in results:
            mi = r.get("_meta_idx")
            if mi is None or mi >= len(metadata):
                continue
            meta = metadata[mi]
            strength = max(float(meta.get("memory_strength", 1)), 0.001)
            last_recall = meta.get("last_recall_date")
            if last_recall:
                try:
                    lr_date = date.fromisoformat(str(last_recall)[:10])
                except ValueError:
                    days = 0.0
                else:
                    days = max(0.0, (ref_date - lr_date).days)
            else:
                days = 0.0
            time_scale = self._config.forgetting_time_scale
            retention = math.exp(-days / (time_scale * strength))
            original_score = max(float(r.get("score", 0.0)), 0.0)
            r["score"] = alpha * original_score + (1.0 - alpha) * retention

        return results

    def _rebuild_bm25_index(self) -> None:
        """从 metadata 重建 BM25 索引（仅包含未被遗忘条目）。"""
        metadata = self._index.get_metadata()
        self._bm25_corpus = []
        self._bm25_meta_indices = []
        for idx, m in enumerate(metadata):
            if not m.get("forgotten"):
                self._bm25_corpus.append(m.get("text", ""))
                self._bm25_meta_indices.append(idx)
        tokenized = [text.lower().split() for text in self._bm25_corpus]
        if tokenized:
            self._bm25_index = BM25Okapi(tokenized)
        else:
            self._bm25_index = None

    def invalidate_bm25(self) -> None:
        """标记 BM25 索引失效，下次搜索时重建。"""
        self._bm25_index = None
