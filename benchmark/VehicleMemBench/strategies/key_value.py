"""键值记忆策略."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import aiofiles

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.paths import (
    setup_vehiclemembench_path as _,  # noqa: F401
)
from benchmark.VehicleMemBench.strategies.exceptions import VehicleMemBenchError

from evaluation.model_evaluation import (  # isort: skip
    MemoryStore as VMBMemoryStore,
    build_memory_kv_for_day,
    process_task_with_kv_memory,
    split_history_by_day,
)

if TYPE_CHECKING:
    from pathlib import Path

    from evaluation.agent_client import AgentClient

logger = logging.getLogger(__name__)


class KeyValueEvaluator:
    """KV 模式评估器：使用预构建的 KV 存储."""

    def __init__(
        self,
        agent_client: AgentClient,
        kv_store: VMBMemoryStore,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        """初始化评估器."""
        self._agent_client = agent_client
        self._kv_store = kv_store
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict[str, Any],
        task_id: int,
        gold_memory: str,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """评估单个 query，使用 KV 存储."""
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_with_kv_memory,
                task,
                task_id,
                self._kv_store,
                self._agent_client,
                self._reflect_num,
            )


class KeyValueMemoryStrategy:
    """键值记忆策略：提取历史中的 KV 对，用于查询评估."""

    @property
    def mode(self) -> BenchMemoryMode:
        """返回策略模式."""
        return BenchMemoryMode.KEY_VALUE

    def needs_history(self) -> bool:
        """是否需要历史文本."""
        return True

    def needs_agent_for_prep(self) -> bool:
        """是否需要 agent client 进行准备."""
        return True

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        """构建 KV 存储，支持断点续传."""
        if agent_client is None:
            msg = f"[key_value] agent_client 为 None，无法 prepare (output_dir={output_dir})"
            raise VehicleMemBenchError(msg)
        daily = split_history_by_day(history_text)
        store = VMBMemoryStore()
        processed_dates: list[str] = []
        daily_snapshots: dict[str, str] = {}
        sorted_dates = sorted(daily.keys())

        partial_file = output_dir / "prep.partial.json"
        try:
            if partial_file.exists():
                async with aiofiles.open(partial_file, encoding="utf-8") as f:
                    partial = json.loads(await f.read())
                store_data = partial.get("store", {})
                store.store = store_data
                processed_dates = partial.get("_processed_dates", [])
                daily_snapshots = partial.get("_daily_snapshots", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("损坏的 partial 文件，从头开始: %s: %s", partial_file, e)
            processed_dates = []
            daily_snapshots = {}

        remaining = [d for d in sorted_dates if d not in processed_dates]

        for date_key in remaining:
            async with semaphore:
                await asyncio.to_thread(
                    build_memory_kv_for_day,
                    agent_client,
                    date_key,
                    daily[date_key],
                    store,
                )
            processed_dates.append(date_key)
            await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
            partial_data = {
                "type": BenchMemoryMode.KEY_VALUE,
                "store": store.to_dict(),
                "_processed_dates": processed_dates,
                "_daily_snapshots": daily_snapshots,
            }
            async with aiofiles.open(partial_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(partial_data, ensure_ascii=False, indent=2))

        if partial_file.exists():
            await asyncio.to_thread(partial_file.unlink)

        return {"type": BenchMemoryMode.KEY_VALUE, "store": store.to_dict()}

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict[str, Any] | None,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> KeyValueEvaluator:
        """创建 KV 模式评估器."""
        store = VMBMemoryStore()
        if prep_data is None:
            msg = f"prep_data 为 None (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.KEY_VALUE
            )
        store_data = prep_data.get("store")
        if store_data is None:
            msg = f"prep_data 缺少 'store' 字段 (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.KEY_VALUE
            )
        if not isinstance(store_data, dict):
            msg = (
                f"prep_data['store'] 类型错误，期望 dict，"
                f"得到 {type(store_data).__name__} (file_num={file_num})"
            )
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.KEY_VALUE
            )
        store.store = store_data
        return KeyValueEvaluator(agent_client, store, reflect_num, query_semaphore)
