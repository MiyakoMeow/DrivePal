"""Query 解析器."""

import strawberry

from app.api.graphql_schema import (
    ExperimentResult as ExperimentResultGQL,
)
from app.api.graphql_schema import (
    ExperimentResults,
    MemoryEventGQL,
    MemoryModeEnum,
    ScenarioPresetGQL,
)
from app.api.resolvers.converters import preset_store, to_gql_preset
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.experiment_store import read_benchmark


@strawberry.type
class Query:
    """GraphQL Query 集合."""

    @strawberry.field
    async def history(
        self,
        limit: int = 10,
        memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK,
        current_user: str = "default",
    ) -> list[MemoryEventGQL]:
        """查询历史记忆事件."""
        mm = get_memory_module()
        mode = MemoryMode(memory_mode.value)
        events = await mm.get_history(limit=limit, mode=mode, user_id=current_user)
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
    async def scenario_presets(
        self,
        current_user: str = "default",
    ) -> list[ScenarioPresetGQL]:
        """查询所有场景预设."""
        store = preset_store(current_user)
        presets = await store.read()
        return [to_gql_preset(p) for p in presets]

    @strawberry.field
    async def experiment_results(self) -> ExperimentResults:
        """查询五策略实验结果对比."""
        data = read_benchmark()
        strategies = []
        for name, metrics in data.get("strategies", {}).items():
            strategies.append(
                ExperimentResultGQL(
                    strategy=name,
                    exact_match=float(metrics.get("exact_match", 0.0)),
                    field_f1=float(metrics.get("field_f1", 0.0)),
                    value_f1=float(metrics.get("value_f1", 0.0)),
                )
            )
        return ExperimentResults(strategies=strategies)
