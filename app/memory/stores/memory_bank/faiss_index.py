"""FAISS 索引管理模块。

提供 FaissIndex 类，封装 FAISS IndexIDMap(IndexFlatIP) 实现余弦相似度检索。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

import faiss
import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.interfaces import VectorIndex

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 1536
_TIMESTAMP_LENGTH = 10


class FaissIndex:
    """FAISS 索引包装器，基于 IndexIDMap(IndexFlatIP) 实现向量检索与元数据管理。"""

    def __init__(
        self, data_dir: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM
    ) -> None:
        """初始化 FaissIndex。

        Args:
            data_dir: 持久化目录（含 index.faiss / metadata.json）。
            embedding_dim: 向量维度，默认 1536。

        """
        self._data_dir = data_dir
        self._dim = embedding_dim
        self._index: faiss.IndexIDMap | None = None
        self._metadata: list[dict] = []
        self._extra: dict = {}
        self._next_id: int = 0
        self._id_to_meta: dict[int, int] = {}

    async def load(self) -> None:
        """从磁盘加载索引与元数据；损坏时不重建，等首次 add_vector 再创建。"""
        if self._index is not None:
            return
        self._data_dir.mkdir(parents=True, exist_ok=True)
        ip = self._data_dir / "index.faiss"
        mp = self._data_dir / "metadata.json"
        ep = self._data_dir / "extra_metadata.json"

        if ip.exists() and mp.exists():
            try:
                idx = faiss.read_index(str(ip))
                meta = cast("list[dict[str, Any]]", json.loads(mp.read_text()))
                if not isinstance(meta, list):
                    msg = "metadata root is not list"
                    raise TypeError(msg)  # noqa: TRY301
                for i, m in enumerate(meta):
                    if not isinstance(m, dict) or "faiss_id" not in m:
                        msg = f"entry {i}: invalid"
                        raise ValueError(msg)  # noqa: TRY301
                if idx.ntotal != len(meta):
                    msg = f"count mismatch {idx.ntotal} vs {len(meta)}"
                    raise ValueError(msg)  # noqa: TRY301
                self._index = idx
                self._dim = idx.d
                self._metadata = meta
                self._next_id = (max(m["faiss_id"] for m in meta) + 1) if meta else 0
                self._id_to_meta = {m["faiss_id"]: i for i, m in enumerate(meta)}
                if ep.exists():
                    e: dict = json.loads(ep.read_text())
                    self._extra = e if isinstance(e, dict) else {}
            except (
                json.JSONDecodeError,
                OSError,
                TypeError,
                ValueError,
                RuntimeError,
            ) as exc:
                logger.warning("FaissIndex corrupted, removing bad files: %s", exc)
                ip.unlink(missing_ok=True)
                mp.unlink(missing_ok=True)
                ep.unlink(missing_ok=True)

    async def save(self) -> None:
        """将索引与元数据持久化到磁盘。"""
        if self._index is None:
            return
        faiss.write_index(self._index, str(self._data_dir / "index.faiss"))
        (self._data_dir / "metadata.json").write_text(
            json.dumps(self._metadata, ensure_ascii=False, indent=2),
        )
        if self._extra:
            (self._data_dir / "extra_metadata.json").write_text(
                json.dumps(self._extra, ensure_ascii=False, indent=2),
            )

    async def add_vector(
        self,
        text: str,
        embedding: list[float],
        timestamp: str,
        extra_meta: dict | None = None,
    ) -> int:
        """添加向量并关联文本与时间戳。

        Args:
            text: 关联文本。
            embedding: 向量。
            timestamp: 时间戳。
            extra_meta: 额外元数据。

        Returns:
            分配的 faiss_id。

        """
        fid = self._next_id
        self._next_id += 1
        emb_dim = len(embedding)
        if self._index is None:
            self._dim = emb_dim
            self._index = faiss.IndexIDMap(faiss.IndexFlatIP(emb_dim))
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        self._index.add_with_ids(vec, np.array([fid], dtype=np.int64))
        entry = {
            "faiss_id": fid,
            "text": text,
            "timestamp": timestamp,
            "memory_strength": 1,
            "last_recall_date": timestamp[:_TIMESTAMP_LENGTH]
            if len(timestamp) >= _TIMESTAMP_LENGTH
            else timestamp,
        }
        if extra_meta:
            entry.update(extra_meta)
        self._metadata.append(entry)
        self._id_to_meta[fid] = len(self._metadata) - 1
        return fid

    async def search(self, query_emb: list[float], top_k: int) -> list[dict]:
        """检索最相似的 top_k 条记忆。

        Args:
            query_emb: 查询向量。
            top_k: 返回条数。

        Returns:
            按相似度降序排列的记忆列表。

        """
        if self._index is None or self._index.ntotal == 0:
            return []
        k = min(top_k, self._index.ntotal)
        vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, k)
        results = []
        for s, fid in zip(scores[0], indices[0], strict=True):
            mi = self._id_to_meta.get(int(fid))
            if mi is None:
                continue
            m = dict(self._metadata[mi])
            m["score"] = float(s)
            m["_meta_idx"] = mi
            results.append(m)
        return results

    async def update_metadata(self, faiss_id: int, updates: dict) -> None:
        """更新指定 faiss_id 的元数据。

        Args:
            faiss_id: 目标 ID。
            updates: 更新的字段。不存在则忽略。

        """
        mi = self._id_to_meta.get(faiss_id)
        if mi is not None:
            self._metadata[mi].update(updates)

    async def remove_vectors(self, faiss_ids: list[int]) -> None:
        """从索引和元数据中移除指定向量。

        Args:
            faiss_ids: 待移除的 ID 列表。

        """
        if self._index is None:  # pragma: no cover
            msg = "index not loaded"
            raise RuntimeError(msg)
        id_arr = np.array(faiss_ids, dtype=np.int64)
        self._index.remove_ids(id_arr)
        id_set = set(faiss_ids)
        self._metadata = [m for m in self._metadata if m["faiss_id"] not in id_set]
        self._id_to_meta = {m["faiss_id"]: i for i, m in enumerate(self._metadata)}

    def get_metadata(self) -> list[dict]:
        """返回所有元数据（可变引用，调用方可修改条目用于遗忘/强化）。"""
        return self._metadata

    def get_metadata_by_id(self, faiss_id: int) -> dict | None:
        """O(1) 按 faiss_id 查找元数据条目。"""
        mi = self._id_to_meta.get(faiss_id)
        if mi is None:
            return None
        return self._metadata[mi]

    def get_extra(self) -> dict:
        """返回额外元数据（总体摘要/人格）。"""
        return self._extra

    def set_extra(self, extra: dict) -> None:  # noqa: D102
        self._extra = extra

    @property
    def total(self) -> int:
        """索引中向量总数。"""
        return self._index.ntotal if self._index else 0
