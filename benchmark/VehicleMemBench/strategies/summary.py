"""递归摘要记忆策略."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.paths import (
    setup_vehiclemembench_path as _,  # noqa: F401
)
from benchmark.VehicleMemBench.strategies.exceptions import VehicleMemBenchError

from evaluation.model_evaluation import (  # isort: skip
    build_memory_recursive_summary,
    process_task_with_memory,
    split_history_by_day,
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
        """构建递归摘要记忆."""
        if agent_client is None:
            msg = f"[summary] agent_client 为 None，无法 prepare (output_dir={output_dir})"
            raise VehicleMemBenchError(msg)
        daily = split_history_by_day(history_text)
        async with semaphore:
            memory_text, _, _ = await asyncio.to_thread(
                build_memory_recursive_summary,
                agent_client,
                daily,
            )
        return {"type": BenchMemoryMode.SUMMARY, "memory": memory_text}

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
