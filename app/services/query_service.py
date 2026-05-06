"""process_query 业务逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from app.agents.workflow import AgentWorkflow
from app.api.graphql_schema import ProcessQueryResult, WorkflowStagesGQL
from app.memory.types import MemoryMode
from app.schemas.context import DrivingContext

if TYPE_CHECKING:
    from app.memory.interfaces import InteractiveMemoryStore


class QueryService:
    """process_query 业务逻辑。mutation resolver 通过此服务委托。"""

    def __init__(self, memory_module: InteractiveMemoryStore) -> None:
        """初始化 QueryService。"""
        self._mm = memory_module

    async def process(
        self,
        query: str,
        context_dict: dict[str, Any] | None,
        mode: str,
    ) -> ProcessQueryResult:
        """处理查询：运行 AgentWorkflow 并返回结果。"""
        workflow = AgentWorkflow(
            memory_mode=MemoryMode(mode),
            memory_module=self._mm,
        )

        driving_context = None
        if context_dict:
            driving_context = DrivingContext(**context_dict).model_dump()

        result, event_id, stages = await workflow.run_with_stages(
            query,
            driving_context,
        )
        return ProcessQueryResult(
            result=result,
            event_id=event_id,
            stages=WorkflowStagesGQL(
                context=cast("Any", stages.context),
                task=cast("Any", stages.task),
                decision=cast("Any", stages.decision),
                execution=cast("Any", stages.execution),
            ),
        )
