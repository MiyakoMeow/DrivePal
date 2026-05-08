"""多用户 FAISS 索引管理模块。

FaissIndex 内部按 user_id 隔离索引/元数据，磁盘布局 {data_dir}/{user_id}/。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 1536
_TIMESTAMP_LENGTH = 10


def _validate_metadata_structure(meta: object) -> list[dict[str, Any]]:
    """校验 metadata 为 list[dict]，每个 dict 含 faiss_id（int，无重复）。"""
    if not isinstance(meta, list):
        msg = "metadata root is not list"
        raise TypeError(msg)
    seen: set[int] = set()
    for i, m in enumerate(meta):
        if not isinstance(m, dict) or "faiss_id" not in m:
            msg = f"entry {i}: invalid"
            raise ValueError(msg)
        entry = cast("dict[str, Any]", m)
        fid: object = entry["faiss_id"]
        if not isinstance(fid, int):
            msg = f"entry {i}: faiss_id={fid!r} 不是整数"
            raise TypeError(msg)
        if fid in seen:
            msg = f"entry {i}: 重复 faiss_id={fid}"
            raise ValueError(msg)
        seen.add(fid)
    return cast("list[dict[str, Any]]", meta)


def _validate_index_count(idx: faiss.Index, meta_len: int) -> None:
    """校验索引条目数与 metadata 数一致。"""
    if idx.ntotal != meta_len:
        msg = f"count mismatch {idx.ntotal} vs {meta_len}"
        raise ValueError(msg)


def _rebuild_speakers(metadata: list[dict]) -> set[str]:
    """从 metadata 重建说话人集合。"""
    speakers: set[str] = set()
    for m in metadata:
        for spk in m.get("speakers", []):
            speakers.add(spk)
    return speakers


def _validate_user_id(user_id: str) -> None:
    """校验 user_id 不含路径遍历字符。"""
    if "/" in user_id or "\\" in user_id or ".." in user_id:
        msg = f"user_id 含非法字符: {user_id!r}"
        raise ValueError(msg)


def _user_dir(data_dir: Path, user_id: str) -> Path:
    """返回指定用户的磁盘目录。"""
    _validate_user_id(user_id)
    return data_dir / user_id


def _clean_user_files(user_dir: Path) -> None:
    """删除用户目录下的三个持久化文件。"""
    for name in ("index.faiss", "metadata.json", "extra_metadata.json"):
        (user_dir / name).unlink(missing_ok=True)


@dataclass
class _UserIndex:
    index: faiss.IndexIDMap
    metadata: list[dict]
    next_id: int
    id_to_meta: dict[int, int]
    all_speakers: set[str]
    extra: dict


class FaissIndex:
    """多用户 FAISS 索引包装器。

    内部按 user_id 隔离索引/元数据。
    磁盘布局: {data_dir}/{user_id}/index.faiss|metadata.json|extra_metadata.json
    """

    def __init__(self, data_dir: Path) -> None:
        """初始化多用户 FAISS 索引。"""
        self._data_dir = data_dir
        self._dim: int | None = None
        self._indices: dict[str, _UserIndex] = {}
        self._loaded = False

    def _ensure_user(self, user_id: str) -> _UserIndex:
        """获取或创建用户索引。"""
        _validate_user_id(user_id)
        if user_id not in self._indices:
            dim = self._dim if self._dim is not None else DEFAULT_EMBEDDING_DIM
            self._indices[user_id] = _UserIndex(
                index=faiss.IndexIDMap(faiss.IndexFlatIP(dim)),
                metadata=[],
                next_id=0,
                id_to_meta={},
                all_speakers=set(),
                extra={},
            )
        return self._indices[user_id]

    def _load_user(self, user_id: str) -> None:
        """从磁盘加载单个用户，损坏时删除文件。"""
        ud = _user_dir(self._data_dir, user_id)
        if not ud.is_dir():
            return
        ip = ud / "index.faiss"
        mp = ud / "metadata.json"
        ep = ud / "extra_metadata.json"

        if not ip.exists() or not mp.exists():
            return

        try:
            idx = faiss.read_index(str(ip))
            raw_meta = json.loads(mp.read_text())
            meta = _validate_metadata_structure(raw_meta)
            _validate_index_count(idx, len(meta))
        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            logger.warning("FaissIndex 用户 %s 数据损坏，删除文件: %s", user_id, exc)
            _clean_user_files(ud)
            return

        id_to_meta = {m["faiss_id"]: i for i, m in enumerate(meta)}
        speakers = _rebuild_speakers(meta)
        extra: dict = {}
        if ep.exists():
            try:
                e: object = json.loads(ep.read_text())
                extra = e if isinstance(e, dict) else {}
            except json.JSONDecodeError, OSError, TypeError, ValueError:
                logger.warning("FaissIndex 用户 %s extra_metadata 损坏，删除", user_id)
                ep.unlink(missing_ok=True)

        if self._dim is None:
            self._dim = idx.d
        elif idx.d != self._dim:
            logger.warning(
                "FaissIndex 用户 %s 维度 %d 与全局 %d 不匹配，跳过加载",
                user_id,
                idx.d,
                self._dim,
            )
            return

        self._indices[user_id] = _UserIndex(
            index=idx,
            metadata=meta,
            next_id=(max(m["faiss_id"] for m in meta) + 1) if meta else 0,
            id_to_meta=id_to_meta,
            all_speakers=speakers,
            extra=extra,
        )

    async def load(self) -> None:
        """扫描 data_dir 子目录，按 user_id 加载。"""
        if self._loaded:
            return
        self._data_dir.mkdir(parents=True, exist_ok=True)
        for child in sorted(self._data_dir.iterdir()):
            if child.is_dir():
                self._load_user(child.name)
        self._loaded = True

    async def reload(self, user_id: str) -> None:
        """重新加载指定用户索引。"""
        if user_id in self._indices:
            del self._indices[user_id]
        self._load_user(user_id)

    async def save(self, user_id: str) -> None:
        """持久化指定用户。"""
        ui = self._indices.get(user_id)
        if ui is None:
            return
        ud = _user_dir(self._data_dir, user_id)
        ud.mkdir(parents=True, exist_ok=True)
        faiss.write_index(ui.index, str(ud / "index.faiss"))
        (ud / "metadata.json").write_text(
            json.dumps(ui.metadata, ensure_ascii=False, indent=2),
        )
        if ui.extra:
            (ud / "extra_metadata.json").write_text(
                json.dumps(ui.extra, ensure_ascii=False, indent=2),
            )
        else:
            (ud / "extra_metadata.json").unlink(missing_ok=True)

    @staticmethod
    def parse_speaker_line(line: str) -> tuple[str | None, str]:
        """从 "Speaker: content" 格式解析说话人和内容。"""
        colon_pos = line.find(": ")
        if colon_pos > 0:
            return line[:colon_pos].strip(), line[colon_pos + 2 :].strip()
        return None, line.strip()

    async def add_vector(
        self,
        user_id: str,
        text: str,
        embedding: list[float],
        timestamp: str,
        extra_meta: dict | None = None,
    ) -> int:
        """向指定用户添加向量，返回 faiss_id。"""
        emb_dim = len(embedding)
        if self._dim is None:
            self._dim = emb_dim
        elif self._dim != emb_dim:
            msg = (
                f"Embedding dimension mismatch: "
                f"index expects {self._dim}-dim, "
                f"but got {emb_dim}-dim vector."
            )
            raise ValueError(msg)

        ui = self._ensure_user(user_id)
        if ui.index.d != emb_dim:
            msg = f"用户 {user_id} 索引维度 {ui.index.d} 与向量维度 {emb_dim} 不匹配"
            raise ValueError(msg)

        fid = ui.next_id
        ui.next_id += 1
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        ui.index.add_with_ids(vec, np.array([fid], dtype=np.int64))

        entry: dict[str, Any] = {
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
            for spk in extra_meta.get("speakers", []):
                ui.all_speakers.add(spk)

        ui.metadata.append(entry)
        ui.id_to_meta[fid] = len(ui.metadata) - 1
        return fid

    async def search(
        self, user_id: str, query_emb: list[float], top_k: int
    ) -> list[dict]:
        """检索指定用户，返回带 _meta_idx 的 dict 列表。"""
        ui = self._indices.get(user_id)
        if ui is None or ui.index.ntotal == 0:
            return []
        k = min(top_k, ui.index.ntotal)
        vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = ui.index.search(vec, k)
        results: list[dict] = []
        for s, fid in zip(scores[0], indices[0], strict=True):
            mi = ui.id_to_meta.get(int(fid))
            if mi is None:
                continue
            m = dict(ui.metadata[mi])
            m["score"] = float(s)
            m["_meta_idx"] = mi
            results.append(m)
        return results

    async def remove_vectors(self, user_id: str, faiss_ids: list[int]) -> None:
        """从指定用户移除向量。"""
        ui = self._indices.get(user_id)
        if ui is None:
            return
        id_arr = np.array(faiss_ids, dtype=np.int64)
        ui.index.remove_ids(id_arr)
        id_set = set(faiss_ids)
        ui.metadata = [m for m in ui.metadata if m["faiss_id"] not in id_set]
        ui.id_to_meta = {m["faiss_id"]: i for i, m in enumerate(ui.metadata)}
        ui.next_id = max((m["faiss_id"] for m in ui.metadata), default=-1) + 1
        ui.all_speakers = _rebuild_speakers(ui.metadata)

    def get_metadata(self, user_id: str) -> list[dict]:
        """返回指定用户的所有元数据。"""
        ui = self._indices.get(user_id)
        return ui.metadata if ui is not None else []

    def get_metadata_by_id(self, user_id: str, faiss_id: int) -> dict | None:
        """按 faiss_id 查找元数据。"""
        ui = self._indices.get(user_id)
        if ui is None:
            return None
        mi = ui.id_to_meta.get(faiss_id)
        if mi is None:
            return None
        return ui.metadata[mi]

    def get_extra(self, user_id: str) -> dict:
        """返回指定用户的额外元数据。"""
        ui = self._indices.get(user_id)
        if ui is None:
            return {}
        return ui.extra if isinstance(ui.extra, dict) else {}

    def set_extra(self, user_id: str, extra: dict) -> None:
        """设置指定用户的额外元数据。"""
        ui = self._indices.get(user_id)
        if ui is not None:
            ui.extra = extra

    def get_all_speakers(self, user_id: str) -> list[str]:
        """返回指定用户的说话人列表。"""
        ui = self._indices.get(user_id)
        if ui is None:
            return []
        if not ui.all_speakers and ui.metadata:
            ui.all_speakers = _rebuild_speakers(ui.metadata)
        return sorted(ui.all_speakers)

    def total(self, user_id: str) -> int:
        """指定用户的向量总数。"""
        ui = self._indices.get(user_id)
        return ui.index.ntotal if ui is not None else 0
