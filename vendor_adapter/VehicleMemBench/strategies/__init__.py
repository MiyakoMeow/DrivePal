"""统一记忆策略 Protocol 与注册表."""

from typing import TYPE_CHECKING, Any, Protocol

from vendor_adapter.VehicleMemBench import BenchMemoryMode  # noqa: TC001
from vendor_adapter.VehicleMemBench.strategies.exceptions import (
    VehicleMemBenchError as VehicleMemBenchError,
)

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

    from evaluation.agent_client import AgentClient


class QueryEvaluator(Protocol):
    """每文件评估器（含一次性初始化资源）."""

    async def evaluate(
        self,
        task: dict[str, Any],
        task_id: int,
        gold_memory: str,
    ) -> dict[str, Any] | None:
        """评估单个 query."""
        ...


class MemoryStrategy(Protocol):
    """统一记忆策略接口."""

    @property
    def mode(self) -> BenchMemoryMode:
        """返回策略对应的记忆模式."""
        ...

    def needs_history(self) -> bool:
        """Prepare 阶段是否需要历史文本."""
        ...

    def needs_agent_for_prep(self) -> bool:
        """Prepare 阶段是否需要 agent client."""
        ...

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        """准备阶段：返回 prep 数据字典（序列化为 prep.json）."""
        ...

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict[str, Any] | None,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> QueryEvaluator:
        """创建每文件评估器."""
        ...


from vendor_adapter.VehicleMemBench.strategies.gold import GoldStrategy  # noqa: E402
from vendor_adapter.VehicleMemBench.strategies.kv import KvMemoryStrategy  # noqa: E402
from vendor_adapter.VehicleMemBench.strategies.memory_bank import (  # noqa: E402
    MemoryBankStrategy,
)
from vendor_adapter.VehicleMemBench.strategies.none import NoneStrategy  # noqa: E402

STRATEGIES: dict[BenchMemoryMode, MemoryStrategy] = {
    s.mode: s
    for s in [NoneStrategy(), GoldStrategy(), KvMemoryStrategy(), MemoryBankStrategy()]
}
