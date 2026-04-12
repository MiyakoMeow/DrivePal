"""无记忆策略."""

import asyncio
from typing import TYPE_CHECKING

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.paths import (
    setup_vehiclemembench_path as _,  # noqa: F401
)

from evaluation.model_evaluation import process_task_direct  # isort: skip

if TYPE_CHECKING:
    from pathlib import Path

    from evaluation.agent_client import AgentClient


class NoneEvaluator:
    """None 模式评估器：不使用历史文本."""

    def __init__(
        self,
        agent_client: AgentClient,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        """初始化评估器."""
        self._agent_client = agent_client
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,  # noqa: ARG002
    ) -> dict | None:
        """评估单个 query，不使用历史."""
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_direct,
                {**task, "history_text": ""},
                task_id,
                self._agent_client,
                self._reflect_num,
            )


class NoneStrategy:
    """无记忆策略：直接调用，不使用任何记忆."""

    @property
    def mode(self) -> BenchMemoryMode:
        """返回策略模式."""
        return BenchMemoryMode.NONE

    def needs_history(self) -> bool:
        """是否需要历史文本."""
        return False

    def needs_agent_for_prep(self) -> bool:
        """是否需要 agent client 进行准备."""
        return False

    async def prepare(
        self,
        history_text: str,  # noqa: ARG002
        output_dir: Path,  # noqa: ARG002
        agent_client: AgentClient | None,  # noqa: ARG002
        semaphore: asyncio.Semaphore,  # noqa: ARG002
    ) -> dict | None:
        """无记忆策略无需准备."""
        return None

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,  # noqa: ARG002
        file_num: int,  # noqa: ARG002
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> NoneEvaluator:
        """创建 None 模式评估器."""
        return NoneEvaluator(agent_client, reflect_num, query_semaphore)
