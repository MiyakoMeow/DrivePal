"""DrivePal MemoryBank 适配器，实现 VehicleMemBench memory-system 接口.

接口契约（8 函数）：
    validate_add_args / validate_test_args / run_add
    build_test_client / init_test_state / close_test_state
    is_test_sequential / format_search_results

设计：
    - 每 thread 持独立 asyncio 事件循环 + MemoryBankStore
    - 每 benchmark file → 独立 user_id（drivepal_{n}）
    - EmbeddingModel 按需创建（避免共享 AsyncOpenAI client）
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Coroutine

from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import MemoryEvent
from app.models.embedding import EmbeddingModel
from app.models.settings import LLMSettings

logger = logging.getLogger(__name__)

TAG = "DRIVEPAL_BANK"
USER_ID_PREFIX = "drivepal"

# 默认 benchmark 数据目录（相对 DrivePal 项目根）
_DEFAULT_DATA_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "vehicle_mem_bench"
)

_T = TypeVar("_T")

# 每步 async 操作超时（秒），防止 Embedding API / FAISS 挂死线程
_CORO_TIMEOUT: float = 120.0

# 显式偏好关键词——含词则 memory_strength=5，否则=3
_PREFERENCE_KEYWORDS: frozenset[str] = frozenset(
    {
        "设置",
        "改成",
        "调",
        "偏好",
        "喜欢",
        "换成",
        "切换",
        "设定",
        "调整",
        "改为",
        "选择",
        "想要",
    }
)

# VehicleMemBench 根目录可覆写（默认与 DrivePal 同级）
# 使用 list 容器避免 PLW0603 global
_VMB_ROOT_OVERRIDE: list[pathlib.Path | None] = [None]


def set_vmb_root(path: str | pathlib.Path | None) -> None:
    """设置 VehicleMemBench 项目根路径。

    用于在 CLI 解析后覆写默认位置（同级目录 VehicleMemBench）。
    不传入或传入 None 则恢复默认。
    """
    _VMB_ROOT_OVERRIDE[0] = None if path is None else pathlib.Path(path).resolve()


def _get_vmb_root() -> pathlib.Path:
    """返回 VehicleMemBench 项目根目录。"""
    override = _VMB_ROOT_OVERRIDE[0]
    if override is not None:
        return override
    drivepal_root = pathlib.Path(__file__).resolve().parent.parent.parent
    return (drivepal_root.parent / "VehicleMemBench").resolve()


def _ensure_vmb_on_path() -> None:
    """确保 VehicleMemBench 在 sys.path 上。"""
    root = _get_vmb_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


# ── MemoryClient ──


class DrivePalMemClient:
    """封装 MemoryBankStore 的同步客户端，供 ThreadPoolExecutor 使用.

    每实例持独立 asyncio 事件循环 + MemoryBankStore，线程安全.
    """

    def __init__(self, data_dir: pathlib.Path, user_id: str) -> None:
        self._data_dir = data_dir
        self._user_id = user_id
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._store: MemoryBankStore | None = None

    # ── 公开接口（同步） ──

    def add(self, content: str, strength: int = 3, **kwargs: object) -> str:
        """写入一条记忆事件."""
        del kwargs
        return self._run(self._async_add(content, strength=strength))

    def search(self, query: str, **kwargs: object) -> list[Any]:
        """搜索记忆，返回 SearchResult 列表."""
        raw_top_k: object = kwargs.get("top_k", 5)
        top_k = int(raw_top_k) if isinstance(raw_top_k, (int, str)) else 5
        return self._run(self._async_search(query, top_k))

    def close(self) -> None:
        """关闭 store 和事件循环."""
        try:
            if self._store is not None:
                self._run(self._store.close())
        except Exception:
            logger.warning("Store close failed", exc_info=True)
        finally:
            self._loop.close()

    # ── 内部 ──

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self._loop.run_until_complete(
            asyncio.wait_for(coro, timeout=_CORO_TIMEOUT)
        )

    async def _ensure_store(self) -> None:
        if self._store is not None:
            return
        settings = LLMSettings.load()
        provider = settings.get_embedding_provider()
        if provider is None:
            msg = "No embedding provider configured"
            raise RuntimeError(msg)
        embedding = EmbeddingModel(provider=provider, batch_size=10)
        self._store = MemoryBankStore(
            data_dir=self._data_dir,
            embedding_model=embedding,
            user_id=self._user_id,
        )

    async def _async_add(self, content: str, strength: int = 3) -> str:
        await self._ensure_store()
        assert self._store is not None
        event = MemoryEvent(
            content=content,
            type="passive_voice",
            created_at=datetime.now(UTC).isoformat(),
            memory_strength=strength,
        )
        return await self._store.write(event)

    async def _async_search(self, query: str, top_k: int) -> list[Any]:
        await self._ensure_store()
        assert self._store is not None
        return await self._store.search(query, top_k)


# ── 公共适配器函数（VehicleMemBench 接口） ──


def _resolve_data_dir(args: object) -> pathlib.Path:
    """解析 benchmark 数据目录。优先 args.memory_url → env → 默认。"""
    raw = getattr(args, "memory_url", None) or os.environ.get("VMB_DATA_DIR")
    if raw:
        return pathlib.Path(raw).resolve()
    return _DEFAULT_DATA_DIR


def validate_add_args(args: object) -> None:
    """验证 add 阶段参数。"""
    history_dir = getattr(args, "history_dir", "")
    if not history_dir or not pathlib.Path(history_dir).is_dir():
        msg = f"history_dir not found: {history_dir}"
        raise FileNotFoundError(msg)


def validate_test_args(args: object) -> None:
    """验证 test 阶段参数。"""
    benchmark_dir = getattr(args, "benchmark_dir", "")
    if not benchmark_dir or not pathlib.Path(benchmark_dir).is_dir():
        msg = f"benchmark_dir not found: {benchmark_dir}"
        raise FileNotFoundError(msg)
    data_dir = _resolve_data_dir(args)
    data_dir.mkdir(parents=True, exist_ok=True)


def run_add(args: object) -> None:
    """将 benchmark 历史对话写入 DrivePal MemoryBank.

    按小时聚合写入，每 hour bucket 一条 MemoryEvent.
    """
    _ensure_vmb_on_path()
    from evaluation.memorysystems.common import (
        collect_history_files,
        load_hourly_history,
        run_add_jobs,
    )

    validate_add_args(args)
    history_dir = pathlib.Path(str(getattr(args, "history_dir", ""))).resolve()
    file_range: str | None = getattr(args, "file_range", None)
    history_files = collect_history_files(str(history_dir), file_range)
    max_workers = getattr(args, "max_workers", 1)
    data_dir = _resolve_data_dir(args)

    logger.info(
        "[%s ADD] history_dir=%s files=%d max_workers=%d data_dir=%s",
        TAG,
        history_dir,
        len(history_files),
        max_workers,
        data_dir,
    )

    def processor(idx: int, history_path: str) -> tuple[int, int, str | None]:
        user_id = f"{USER_ID_PREFIX}_{idx}"
        user_data_dir = data_dir / user_id
        user_data_dir.mkdir(parents=True, exist_ok=True)
        client = DrivePalMemClient(data_dir=user_data_dir, user_id=user_id)
        message_count = 0
        try:
            for bucket in load_hourly_history(history_path):
                content = "\n".join(bucket.lines)
                strength = 5 if any(kw in content for kw in _PREFERENCE_KEYWORDS) else 3
                client.add(content=content, strength=strength)
                message_count += 1
        except Exception as exc:
            return idx, message_count, str(exc)
        else:
            return idx, message_count, None
        finally:
            client.close()

    run_add_jobs(
        history_files=history_files,
        tag=TAG,
        max_workers=max_workers,
        processor=processor,
    )


def init_test_state(
    args: object, _file_numbers: object, _user_id_prefix: object
) -> dict[str, Any]:
    """初始化共享状态：创建数据目录 + 客户端注册表。"""
    data_dir = _resolve_data_dir(args)
    return {"data_dir": data_dir, "clients": [], "_lock": threading.Lock()}


def build_test_client(
    _args: object,
    file_num: int,
    user_id_prefix: str,
    shared_state: dict,
) -> DrivePalMemClient:
    """为指定文件创建 DrivePalMemClient."""
    data_dir = shared_state["data_dir"]
    user_id = f"{user_id_prefix}_{file_num}"
    user_data_dir = data_dir / user_id
    user_data_dir.mkdir(parents=True, exist_ok=True)
    client = DrivePalMemClient(data_dir=user_data_dir, user_id=user_id)
    lock: threading.Lock = shared_state["_lock"]
    with lock:
        shared_state["clients"].append(client)
    return client


def close_test_state(shared_state: dict) -> None:
    """关闭所有打开的客户端。"""
    for client in shared_state.get("clients", []):
        try:
            client.close()
        except Exception:
            logger.warning("Failed to close DrivePalMemClient", exc_info=True)


def is_test_sequential() -> bool:
    """每文件独立 user 目录，可并行。"""
    return False


def format_search_results(search_result: object) -> tuple[str, int]:
    """将 SearchResult 列表格式化为文本。

    Returns:
        (格式化文本, 条目数)

    """
    if not isinstance(search_result, list):
        return "", 0
    texts: list[str] = []
    for r in search_result:
        ev = getattr(r, "event", None)
        if isinstance(ev, dict):
            content = ev.get("content", "")
        elif isinstance(ev, str):
            content = ev
        else:
            content = str(r)
        if not content:
            continue
        score = getattr(r, "score", 0.0)
        texts.append(f"[score={score:.3f}] {content}")
    if not texts:
        return "", 0
    return "\n\n".join(texts), len(texts)
