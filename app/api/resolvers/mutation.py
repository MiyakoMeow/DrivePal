"""Mutation 解析器."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal, cast

import strawberry
from graphql.error import GraphQLError

from app.api.graphql_schema import (
    FeedbackInput,
    FeedbackResult,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
)
from app.api.resolvers._converters import preset_dict_to_gql
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.context import (
    DrivingContext,
    ScenarioPreset,
)
from app.schemas.context_converter import input_to_context_dict
from app.services import create_preset_service
from app.services.query_service import QueryService

if TYPE_CHECKING:
    from app.memory.interfaces import InteractiveMemoryStore

_preset_svc = create_preset_service()
_query_svc = QueryService(
    memory_module=cast("InteractiveMemoryStore", get_memory_module()),
)


class InternalServerError(GraphQLError):
    """内部服务器错误."""

    def __init__(self) -> None:
        """初始化内部服务器错误."""
        super().__init__("Internal server error")


class GraphQLInvalidActionError(GraphQLError):
    """无效的操作类型."""

    def __init__(self, action: str) -> None:
        """初始化无效操作错误."""
        super().__init__(f"Invalid action: {action!r}")


class GraphQLEventNotFoundError(GraphQLError):
    """事件不存在."""

    def __init__(self, event_id: str) -> None:
        """初始化事件不存在错误."""
        super().__init__(f"Event not found: {event_id!r}")


logger = logging.getLogger(__name__)


@strawberry.type
class Mutation:
    """GraphQL Mutation 集合."""

    @strawberry.mutation
    async def process_query(
        self,
        query_input: Annotated[ProcessQueryInput, strawberry.argument(name="input")],
    ) -> ProcessQueryResult:
        """处理用户查询并返回工作流结果."""
        try:
            ctx_dict = None
            if query_input.context:
                ctx_dict = input_to_context_dict(query_input.context)
            return await _query_svc.process(
                query=query_input.query,
                context_dict=ctx_dict,
                mode=query_input.memory_mode.value,
            )
        except GraphQLError:
            raise
        except Exception as e:
            logger.exception("processQuery failed")
            raise InternalServerError from e

    @strawberry.mutation
    async def submit_feedback(
        self,
        feedback_input: Annotated[FeedbackInput, strawberry.argument(name="input")],
    ) -> FeedbackResult:
        """提交用户反馈."""
        if feedback_input.action not in ("accept", "ignore"):
            raise GraphQLInvalidActionError(feedback_input.action)
        try:
            mm = get_memory_module()
            safe_action: Literal["accept", "ignore"]
            safe_action = "accept" if feedback_input.action == "accept" else "ignore"
            mode = MemoryMode(feedback_input.memory_mode.value)
            actual_type = await mm.get_event_type(
                feedback_input.event_id,
                mode=mode,
            )
        except Exception as e:
            logger.exception("submitFeedback failed")
            raise InternalServerError from e

        if actual_type is None:
            raise GraphQLEventNotFoundError(feedback_input.event_id)

        try:
            feedback = FeedbackData(
                action=safe_action,
                type=actual_type,
                modified_content=feedback_input.modified_content,
            )
            await mm.update_feedback(feedback_input.event_id, feedback, mode=mode)
        except GraphQLError:
            raise
        except Exception as e:
            logger.exception("submitFeedback failed")
            raise InternalServerError from e

        return FeedbackResult(status="success")

    @strawberry.mutation
    async def save_scenario_preset(
        self,
        preset_input: Annotated[ScenarioPresetInput, strawberry.argument(name="input")],
    ) -> ScenarioPresetGQL:
        """保存场景预设."""
        preset = ScenarioPreset(name=preset_input.name)
        if preset_input.context:
            preset.context = DrivingContext(
                **input_to_context_dict(preset_input.context)
            )
        await _preset_svc.save(preset.model_dump())
        return preset_dict_to_gql(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(self, preset_id: str) -> bool:
        """删除场景预设."""
        return await _preset_svc.delete(preset_id)
