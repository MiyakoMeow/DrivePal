"""Query 解析器."""

import strawberry

from app.api.graphql_schema import (
    MemoryEventGQL,
    ScenarioPresetGQL,
)
from app.api.resolvers.mutation import (
    GraphQLInvalidUserIDError,
    _preset_store,
    _to_gql_preset,
)
from app.memory.memory_bank.faiss_index import FaissIndexManager
from app.memory.singleton import get_memory_store


@strawberry.type
class Query:
    """GraphQL Query 集合."""

    @strawberry.field
    async def history(
        self,
        limit: int = 10,
        user_id: str = "default",
    ) -> list[MemoryEventGQL]:
        """查询历史记忆事件."""
        try:
            FaissIndexManager.validate_user_id(user_id)
        except ValueError:
            raise GraphQLInvalidUserIDError(user_id) from None
        mm = get_memory_store()
        events = await mm.get_history(user_id=user_id, limit=limit)
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
    async def scenario_presets(self) -> list[ScenarioPresetGQL]:
        """查询所有场景预设."""
        store = _preset_store()
        presets = await store.read()
        return [_to_gql_preset(p) for p in presets]
