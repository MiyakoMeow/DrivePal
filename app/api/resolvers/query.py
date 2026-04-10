"""Query 解析器."""

import strawberry

from app.api.graphql_schema import (
    ExperimentReport,
    MemoryEventGQL,
    MemoryModeEnum,
    ScenarioPresetGQL,
)
from app.api.resolvers.mutation import _preset_store, _to_gql_preset
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode


@strawberry.type
class Query:
    """GraphQL Query 集合."""

    @strawberry.field
    async def history(
        self,
        limit: int = 10,
        memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK,
    ) -> list[MemoryEventGQL]:
        """查询历史记忆事件."""
        mm = get_memory_module()
        mode = MemoryMode(memory_mode.value)
        events = await mm.get_history(limit=limit, mode=mode)
        return [
            MemoryEventGQL(
                id=e.id,
                content=e.content,
                type=e.type,
                description=e.description,
                created_at=e.created_at,
            )
            for e in events
        ]

    @strawberry.field
    def experiment_report(self) -> ExperimentReport:
        """获取实验报告."""
        return ExperimentReport(report="Experiment runner migrated to CLI pipeline")

    @strawberry.field
    async def scenario_presets(self) -> list[ScenarioPresetGQL]:
        """查询所有场景预设."""
        store = _preset_store()
        presets = await store.read()
        return [_to_gql_preset(p) for p in presets]
