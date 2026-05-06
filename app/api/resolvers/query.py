"""Query 解析器."""

import strawberry

from app.api.graphql_schema import (
    ExperimentReport,
    MemoryEventGQL,
    MemoryModeGQL,
    ScenarioPresetGQL,
)
from app.api.resolvers._converters import preset_dict_to_gql
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.services import create_preset_service

_preset_svc = create_preset_service()


@strawberry.type
class Query:
    """GraphQL Query 集合."""

    @strawberry.field
    async def history(
        self,
        limit: int = 10,
        memory_mode: MemoryModeGQL = MemoryModeGQL.MEMORY_BANK,  # type: ignore[assignment]
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
        presets = await _preset_svc.list_all()
        return [preset_dict_to_gql(p) for p in presets]
