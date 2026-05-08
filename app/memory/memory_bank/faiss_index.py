"""多用户 FAISS 索引管理器。

替代原单用户 FaissIndex，支持 per-user 索引隔离：
  data_dir/
    user_{user_id}/
      index.faiss
      metadata.json
      extra_metadata.json
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import faiss
import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 1536
_TIMESTAMP_LENGTH = 10
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


@dataclass
class _UserIndex:
    """单用户的 FAISS 索引 + 元数据。"""

    index: faiss.IndexIDMap
    metadata: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 0
    id_to_meta: dict[int, int] = field(default_factory=dict)
    speakers: set[str] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)


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
        entry: dict[str, Any] = cast("dict[str, Any]", m)
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


class FaissIndexManager:
    """多用户 FAISS 索引管理器。

    每个 user_id 对应独立 _UserIndex，存储在 data_dir/user_{user_id}/ 下。
    支持延迟加载、deep copy metadata、per-user extra。
    """

    def __init__(
        self, data_dir: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM
    ) -> None:
        self._data_dir = data_dir
        self._dim = embedding_dim
        self._users: dict[str, _UserIndex] = {}

    # ── 用户目录 ──

    def _user_dir(self, user_id: str) -> Path:
        self.validate_user_id(user_id)
        return self._data_dir / f"user_{user_id}"

    # ── 加载/保存 ──

    async def load(self, user_id: str) -> None:
        """延迟加载；已加载则跳过。"""
        if user_id in self._users:
            return
        user_dir = self._user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        ip = user_dir / "index.faiss"
        mp = user_dir / "metadata.json"
        ep = user_dir / "extra_metadata.json"

        if ip.exists() and mp.exists():
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
                logger.warning(
                    "FaissIndexManager: 损坏 user=%s，重建空索引: %s", user_id, exc
                )
                ip.unlink(missing_ok=True)
                mp.unlink(missing_ok=True)
                ep.unlink(missing_ok=True)
                self._users[user_id] = _UserIndex(
                    index=faiss.IndexIDMap(faiss.IndexFlatIP(self._dim))
                )
                return
            ui = _UserIndex(
                index=idx,
                metadata=meta,
                next_id=max(m["faiss_id"] for m in meta) + 1 if meta else 0,
                id_to_meta={m["faiss_id"]: i for i, m in enumerate(meta)},
            )
            self._rebuild_speakers(ui)
            if ep.exists():
                try:
                    e = json.loads(ep.read_text())
                    ui.extra = e if isinstance(e, dict) else {}
                except json.JSONDecodeError, OSError, TypeError, ValueError:
                    ep.unlink(missing_ok=True)
            self._users[user_id] = ui
        else:
            ui = _UserIndex(index=faiss.IndexIDMap(faiss.IndexFlatIP(self._dim)))
            if ep.exists():
                try:
                    e = json.loads(ep.read_text())
                    ui.extra = e if isinstance(e, dict) else {}
                except json.JSONDecodeError, OSError, TypeError, ValueError:
                    ep.unlink(missing_ok=True)
            self._users[user_id] = ui

    async def save(self, user_id: str) -> None:
        """持久化索引 + metadata + extra。"""
        ui = self._users.get(user_id)
        if ui is None:
            return
        if ui.index.ntotal == 0 and not ui.metadata:
            user_dir = self._user_dir(user_id)
            # 有 extra 则持久化（不走清理）
            ep = user_dir / "extra_metadata.json"
            if ui.extra:
                user_dir.mkdir(parents=True, exist_ok=True)
                ep.write_text(json.dumps(ui.extra, ensure_ascii=False, indent=2))
            else:
                ep.unlink(missing_ok=True)
            # 清理索引/metadata 文件（空索引无需保留）
            for fname in ("index.faiss", "metadata.json"):
                (user_dir / fname).unlink(missing_ok=True)
            return
        user_dir = self._user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(ui.index, str(user_dir / "index.faiss"))
        (user_dir / "metadata.json").write_text(
            json.dumps(ui.metadata, ensure_ascii=False, indent=2)
        )
        ep = user_dir / "extra_metadata.json"
        if ui.extra:
            ep.write_text(json.dumps(ui.extra, ensure_ascii=False, indent=2))
        else:
            ep.unlink(missing_ok=True)

    # ── 向量操作 ──

    async def add_vector(
        self,
        user_id: str,
        text: str,
        embedding: list[float],
        timestamp: str,
        extra_meta: dict | None = None,
    ) -> int:
        """添加向量并关联文本与时间戳。返回 faiss_id。"""
        if user_id not in self._users:
            await self.load(user_id)
        ui = self._users[user_id]
        emb_dim = len(embedding)
        if ui.index.d != emb_dim:
            if ui.index.ntotal == 0:
                ui.index = faiss.IndexIDMap(faiss.IndexFlatIP(emb_dim))
            else:
                msg = (
                    f"Embedding dimension mismatch: "
                    f"index expects {ui.index.d}-dim, "
                    f"but got {emb_dim}-dim vector."
                )
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
                ui.speakers.add(spk)
        ui.metadata.append(entry)
        ui.id_to_meta[fid] = len(ui.metadata) - 1
        return fid

    async def search(
        self, user_id: str, query_emb: list[float], top_k: int
    ) -> list[dict]:
        """检索最相似的 top_k 条记忆。结果含 _meta_idx/text/score/timestamp 等字段。"""
        ui = self._users.get(user_id)
        if ui is None or ui.index.ntotal == 0:
            return []
        k = min(top_k, ui.index.ntotal)
        vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = ui.index.search(vec, k)
        results = []
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
        """删除向量并同步 next_id/id_to_meta/speakers。next_id 单调递增，不复用已删除 ID。"""
        ui = self._users.get(user_id)
        if ui is None:
            return
        ui.index.remove_ids(np.array(faiss_ids, dtype=np.int64))
        id_set = set(faiss_ids)
        ui.metadata = [m for m in ui.metadata if m["faiss_id"] not in id_set]
        ui.id_to_meta = {m["faiss_id"]: i for i, m in enumerate(ui.metadata)}
        ui.next_id = max((m["faiss_id"] for m in ui.metadata), default=-1) + 1
        self._rebuild_speakers(ui)

    # ── metadata 访问（不可变保护）──

    def get_metadata(self, user_id: str) -> list[dict]:
        """返回 metadata 的 deep copy。外部修改不影响内部状态。"""
        ui = self._users.get(user_id)
        if ui is None:
            return []
        return copy.deepcopy(ui.metadata)

    async def update_metadata(self, user_id: str, faiss_id: int, updates: dict) -> None:
        """显式更新单条 metadata。"""
        ui = self._users.get(user_id)
        if ui is None:
            return
        mi = ui.id_to_meta.get(faiss_id)
        if mi is not None:
            ui.metadata[mi].update(updates)
            if "speakers" in updates:
                self._rebuild_speakers(ui)

    async def batch_update_metadata(
        self, user_id: str, updates: dict[int, dict]
    ) -> None:
        """批量更新 {meta_idx: {field: value}}。"""
        ui = self._users.get(user_id)
        if ui is None:
            return
        for meta_idx, fields in updates.items():
            if 0 <= meta_idx < len(ui.metadata):
                ui.metadata[meta_idx].update(fields)
        if any("speakers" in fields for fields in updates.values()):
            self._rebuild_speakers(ui)

    def get_metadata_by_id(self, user_id: str, faiss_id: int) -> dict | None:
        """O(1) 按 faiss_id 查找。"""
        ui = self._users.get(user_id)
        if ui is None:
            return None
        mi = ui.id_to_meta.get(faiss_id)
        return dict(ui.metadata[mi]) if mi is not None else None

    # ── extra metadata（可变引用）──

    def get_extra(self, user_id: str) -> dict:
        """返回 extra metadata 的**可变引用**。调用方可原地修改，由 save 持久化。"""
        ui = self._users.get(user_id)
        if ui is None:
            return {}
        return ui.extra

    # ── 统计 ──

    async def total(self, user_id: str) -> int:
        """索引中向量总数。"""
        ui = self._users.get(user_id)
        return ui.index.ntotal if ui is not None else 0

    def is_loaded(self, user_id: str) -> bool:
        """是否已加载。"""
        return user_id in self._users

    def get_all_speakers(self, user_id: str) -> list[str]:
        """返回所有已知说话人列表。"""
        ui = self._users.get(user_id)
        return sorted(ui.speakers) if ui is not None else []

    # ── 静态方法 ──

    @staticmethod
    def validate_user_id(user_id: str) -> None:
        """校验 user_id 合法性，防路径穿越。只允许字母数字_ . -，非空、首字符不可为 . 或 -。"""
        if not user_id or not _USER_ID_PATTERN.match(user_id):
            msg = f"Invalid user_id: {user_id!r}"
            raise ValueError(msg)

    @staticmethod
    def parse_speaker_line(line: str) -> tuple[str | None, str]:
        """从 "Speaker: content" 格式解析说话人和内容。"""
        colon_pos = line.find(": ")
        if colon_pos > 0:
            return line[:colon_pos].strip(), line[colon_pos + 2 :].strip()
        return None, line.strip()

    # ── 内部 ──

    @staticmethod
    def _rebuild_speakers(ui: _UserIndex) -> None:
        """从 metadata 重建 speakers 缓存。"""
        ui.speakers.clear()
        for m in ui.metadata:
            for spk in m.get("speakers", []):
                ui.speakers.add(spk)
