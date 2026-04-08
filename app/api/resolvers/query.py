"""Query resolvers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import strawberry

if TYPE_CHECKING:
    from app.memory.memory import MemoryModule

from app.api.graphql_schema import (
    ExperimentReport,
    MemoryEventGQL,
    MemoryModeEnum,
    ScenarioPresetGQL,
)
from app.memory.types import MemoryMode


def _get_memory_module(info: strawberry.Info) -> MemoryModule:
    return info.context["memory_module"]


@strawberry.type
class Query:
    """GraphQL Query 集合."""

    @strawberry.field
    async def history(
        self,
        info: strawberry.Info,
        limit: int = 10,
        memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK,
    ) -> list[MemoryEventGQL]:
        """查询历史记忆事件."""
        mm = _get_memory_module(info)
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
    async def scenario_presets(self, info: strawberry.Info) -> list[ScenarioPresetGQL]:
        """查询所有场景预设."""
        from app.api.resolvers.mutation import _preset_store, _to_gql_preset

        store = _preset_store(info)
        presets = await store.read()
        return [_to_gql_preset(p) for p in presets]
