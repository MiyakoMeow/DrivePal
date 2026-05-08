"""Mutation 解析器."""

import dataclasses
import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import strawberry
from graphql.error import GraphQLError

if TYPE_CHECKING:
    from collections.abc import Awaitable

from app.agents.workflow import AgentWorkflow
from app.api.graphql_schema import (
    DriverStateGQL,
    DrivingContextGQL,
    DrivingContextInput,
    FeedbackInput,
    FeedbackResult,
    GeoLocationGQL,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
    WorkflowStagesGQL,
)
from app.config import DATA_DIR
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.context import (
    DrivingContext,
    ScenarioPreset,
)
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)


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


def _preset_store() -> TOMLStore:
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def _strawberry_to_plain(obj: object) -> object:
    """递归将 Strawberry 类型转普通 Python 对象（Enum→.value，dataclass→dict）。

    跳过 None 值字段，避免 Pydantic 对非 Optional 字段收到 None 引发验证错误。
    结果可直接喂给 Pydantic model_validate。
    """
    if obj is None or isinstance(obj, (str, bytes, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [_strawberry_to_plain(item) for item in obj]
    if dataclasses.is_dataclass(obj):
        return {
            f.name: _strawberry_to_plain(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if getattr(obj, f.name) is not None
        }
    return obj


def _input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    """将 Strawberry GraphQL input 转为 Pydantic DrivingContext。"""
    data = cast("dict[str, Any]", _strawberry_to_plain(input_obj))
    # None 值不传入，让 Pydantic 使用字段默认值
    return DrivingContext.model_validate(
        {k: v for k, v in data.items() if v is not None},
    )


def _dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    """Convert dict to DrivingContextGQL via Pydantic validation."""
    ctx = DrivingContext.model_validate(d)
    dest = ctx.spatial.destination
    return DrivingContextGQL(
        driver=DriverStateGQL(
            emotion=ctx.driver.emotion,
            workload=ctx.driver.workload,
            fatigue_level=ctx.driver.fatigue_level,
        ),
        spatial=SpatioTemporalContextGQL(
            current_location=GeoLocationGQL(
                latitude=ctx.spatial.current_location.latitude,
                longitude=ctx.spatial.current_location.longitude,
                address=ctx.spatial.current_location.address,
                speed_kmh=ctx.spatial.current_location.speed_kmh,
            ),
            destination=GeoLocationGQL(
                latitude=dest.latitude,
                longitude=dest.longitude,
                address=dest.address,
                speed_kmh=dest.speed_kmh,
            )
            if dest is not None
            else None,
            eta_minutes=ctx.spatial.eta_minutes,
            heading=ctx.spatial.heading,
        ),
        traffic=TrafficConditionGQL(
            congestion_level=ctx.traffic.congestion_level,
            incidents=ctx.traffic.incidents,
            estimated_delay_minutes=ctx.traffic.estimated_delay_minutes,
        ),
        scenario=ctx.scenario,
    )


def _to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        # TOML 存储将 None 转空字符串，读取时恢复
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=_dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )


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
                driving_context = _input_to_context(query_input.context).model_dump()

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
        return FeedbackResult(status="success")

    @strawberry.mutation
    async def save_scenario_preset(
        self,
        preset_input: Annotated[ScenarioPresetInput, strawberry.argument(name="input")],
    ) -> ScenarioPresetGQL:
        """保存场景预设."""
        store = _preset_store()
        preset = ScenarioPreset(name=preset_input.name)
        if preset_input.context:
            preset.context = _input_to_context(preset_input.context)
        await store.append(preset.model_dump())
        return _to_gql_preset(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(self, preset_id: str) -> bool:
        """删除场景预设."""
        store = _preset_store()
        presets = await store.read()
        new_presets = [p for p in presets if p.get("id") != preset_id]
        if len(new_presets) == len(presets):
            return False
        await store.write(new_presets)
        return True
