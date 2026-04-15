"""递归摘要记忆策略."""

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
    process_task_with_memory,
    split_history_by_day,
    summarize_day_with_previous_memory,
)

if TYPE_CHECKING:
    from pathlib import Path

    from evaluation.agent_client import AgentClient

logger = logging.getLogger(__name__)


class SummaryEvaluator:
    """Summary 模式评估器：使用预构建的摘要记忆."""

    def __init__(
        self,
        agent_client: AgentClient,
        memory_text: str,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        """初始化评估器."""
        self._agent_client = agent_client
        self._memory_text = memory_text
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict[str, Any],
        task_id: int,
        gold_memory: str,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """评估单个 query，使用摘要记忆."""
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_with_memory,
                task,
                task_id,
                self._memory_text,
                self._agent_client,
                self._reflect_num,
            )


class SummaryMemoryStrategy:
    """递归摘要记忆策略：LLM 逐日构建递归摘要，用于查询评估."""

    @property
    def mode(self) -> BenchMemoryMode:
        """返回策略模式."""
        return BenchMemoryMode.SUMMARY

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
        """构建递归摘要记忆，支持断点续传."""
        if agent_client is None:
            msg = f"[summary] agent_client 为 None，无法 prepare (output_dir={output_dir})"
            raise VehicleMemBenchError(msg)
        daily = split_history_by_day(history_text)
        accumulated_memory = ""
        processed_dates: list[str] = []
        daily_snapshots: dict[str, str] = {}
        sorted_dates = sorted(daily.keys())

        partial_file = output_dir / "prep.partial.json"
        try:
            if await asyncio.to_thread(partial_file.exists):
                async with aiofiles.open(partial_file, encoding="utf-8") as f:
                    partial = json.loads(await f.read())
                accumulated_memory = partial.get("memory", "")
                processed_dates = partial.get("_processed_dates", [])
                daily_snapshots = partial.get("_daily_snapshots", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("损坏的 partial 文件，从头开始: %s: %s", partial_file, e)
            processed_dates = []
            daily_snapshots = {}

        remaining = [d for d in sorted_dates if d not in processed_dates]

        for date_key in remaining:
            async with semaphore:
                accumulated_memory, _, _ = await asyncio.to_thread(
                    summarize_day_with_previous_memory,
                    agent_client,
                    date_key,
                    daily[date_key],
                    accumulated_memory,
                )
            processed_dates.append(date_key)
            daily_snapshots[date_key] = accumulated_memory
            await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
            partial_data = {
                "type": BenchMemoryMode.SUMMARY,
                "memory": accumulated_memory,
                "_processed_dates": processed_dates,
                "_daily_snapshots": daily_snapshots,
            }
            async with aiofiles.open(partial_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(partial_data, ensure_ascii=False, indent=2))

        if await asyncio.to_thread(partial_file.exists):
            await asyncio.to_thread(partial_file.unlink)

        return {"type": BenchMemoryMode.SUMMARY, "memory": accumulated_memory}

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict[str, Any] | None,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> SummaryEvaluator:
        """创建 Summary 模式评估器."""
        if prep_data is None:
            msg = f"prep_data 为 None (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.SUMMARY
            )
        prep_type = prep_data.get("type")
        if prep_type != BenchMemoryMode.SUMMARY:
            msg = (
                f"prep_data['type'] 不匹配，期望 {BenchMemoryMode.SUMMARY}，"
                f"得到 {prep_type} (file_num={file_num})"
            )
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.SUMMARY
            )
        memory_text = prep_data.get("memory")
        if memory_text is None:
            msg = f"prep_data 缺少 'memory' 字段 (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.SUMMARY
            )
        if not isinstance(memory_text, str):
            msg = (
                f"prep_data['memory'] 类型错误，期望 str，"
                f"得到 {type(memory_text).__name__} (file_num={file_num})"
            )
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.SUMMARY
            )
        return SummaryEvaluator(agent_client, memory_text, reflect_num, query_semaphore)
