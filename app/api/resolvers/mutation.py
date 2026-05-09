"""Mutation 解析器."""

import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import strawberry
from graphql.error import GraphQLError

if TYPE_CHECKING:
    from collections.abc import Awaitable

from app.agents.workflow import AgentWorkflow
from app.api.graphql_schema import (
    FeedbackInput,
    FeedbackResult,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    WorkflowStagesGQL,
)
from app.api.resolvers.converters import (
    input_to_context,
    preset_store,
    to_gql_preset,
)
from app.api.resolvers.errors import (
    GraphQLEventNotFoundError,
    GraphQLInvalidActionError,
    InternalServerError,
)
from app.config import DATA_DIR, user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.context import (
    ScenarioPreset,
)
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)


async def _safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 GraphQLError.

    Args:
        coro: 待执行的异步调用。
        context_msg: 异常日志上下文描述。

    Returns:
        调用结果。

    Raises:
        GraphQLError: 所有记忆层异常包装后抛出。

    """
    try:
        return await coro
    except GraphQLError:
        raise
    except OSError as e:
        msg = "Internal storage error"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except RuntimeError as e:
        msg = "Internal runtime error"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except ValueError as e:
        msg = f"Invalid data in {context_msg}"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise InternalServerError from e


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
            mm = get_memory_module()
            workflow = AgentWorkflow(
                data_dir=DATA_DIR,
                memory_mode=MemoryMode(query_input.memory_mode.value),
                memory_module=mm,
            )

            driving_context = None
            if query_input.context:
                driving_context = input_to_context(query_input.context).model_dump()

            result, event_id, stages = await workflow.run_with_stages(
                query_input.query,
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
        except Exception as e:
            logger.exception("submitFeedback failed (get_memory_module)")
            raise InternalServerError from e
        safe_action: Literal["accept", "ignore"]
        safe_action = "accept" if feedback_input.action == "accept" else "ignore"
        mode = MemoryMode(feedback_input.memory_mode.value)

        actual_type = await _safe_memory_call(
            mm.get_event_type(feedback_input.event_id, mode=mode),
            "submitFeedback(get_event_type)",
        )

        if actual_type is None:
            raise GraphQLEventNotFoundError(feedback_input.event_id)

        feedback = FeedbackData(
            action=safe_action,
            type=actual_type,
            modified_content=feedback_input.modified_content,
        )
        await _safe_memory_call(
            mm.update_feedback(feedback_input.event_id, feedback, mode=mode),
            "submitFeedback(update_feedback)",
        )

        # 更新 reminder_weights（反馈学习）
        current_user = getattr(feedback_input, "current_user", None) or "default"
        user_dir = user_data_dir(current_user)
        strategy_store = TOMLStore(
            user_dir=user_dir,
            filename="strategies.toml",
            default_factory=dict,
        )
        await strategy_store.read()  # 确保文件存在
        current_strategy = await strategy_store.read()
        weights = current_strategy.get("reminder_weights", {})
        delta = 0.1 if safe_action == "accept" else -0.1
        new_weight = weights.get(actual_type, 0.5) + delta
        weights[actual_type] = max(0.1, min(1.0, new_weight))
        await strategy_store.update("reminder_weights", weights)

        return FeedbackResult(status="success")

    @strawberry.mutation
    async def save_scenario_preset(
        self,
        preset_input: Annotated[ScenarioPresetInput, strawberry.argument(name="input")],
    ) -> ScenarioPresetGQL:
        """保存场景预设."""
        store = preset_store()
        preset = ScenarioPreset(name=preset_input.name)
        if preset_input.context:
            preset.context = input_to_context(preset_input.context)
        await store.append(preset.model_dump())
        return to_gql_preset(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(self, preset_id: str) -> bool:
        """删除场景预设."""
        store = preset_store()
        presets = await store.read()
        new_presets = [p for p in presets if p.get("id") != preset_id]
        if len(new_presets) == len(presets):
            return False
        await store.write(new_presets)
        return True
