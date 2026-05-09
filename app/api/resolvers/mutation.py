"""Mutation 解析器."""

import logging
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import strawberry
from graphql.error import GraphQLError

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from strawberry.scalars import JSON

from app.agents.conversation import _conversation_manager
from app.agents.pending import PendingReminderManager
from app.agents.workflow import AgentWorkflow, ChatModelUnavailableError
from app.api.graphql_schema import (
    DrivingContextInput,
    ExportDataResult,
    FeedbackInput,
    FeedbackResult,
    PendingReminderGQL,
    PollResult,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    TriggeredReminderGQL,
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
                current_user=query_input.current_user,
            )

            driving_context = None
            if query_input.context:
                driving_context = input_to_context(query_input.context).model_dump()

            result, event_id, stages = await workflow.run_with_stages(
                query_input.query,
                driving_context,
                session_id=query_input.session_id,
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
        # ChatModelUnavailableError 也可能不经 _safe_memory_call
        # 直接由 workflow._call_llm_json 抛出，此处兜底。
        except ChatModelUnavailableError as e:
            msg = "AI 模型未就绪"
            raise GraphQLError(
                msg,
                extensions={"code": "CHAT_MODEL_UNAVAILABLE"},
            ) from e
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

        current_user = feedback_input.current_user

        feedback = FeedbackData(
            action=safe_action,
            type=actual_type,
            modified_content=feedback_input.modified_content,
        )
        await _safe_memory_call(
            mm.update_feedback(
                feedback_input.event_id,
                feedback,
                mode=mode,
                user_id=current_user,
            ),
            "submitFeedback(update_feedback)",
        )

        # 权重更新：读→改→写 strategies.toml
        user_dir = user_data_dir(current_user)
        strategy_store = TOMLStore(
            user_dir=user_dir,
            filename="strategies.toml",
            default_factory=dict,
        )
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
        store = preset_store(preset_input.current_user)
        preset = ScenarioPreset(name=preset_input.name)
        if preset_input.context:
            preset.context = input_to_context(preset_input.context)
        await store.append(preset.model_dump())
        return to_gql_preset(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(
        self,
        preset_id: str,
        current_user: str = "default",
    ) -> bool:
        """删除场景预设."""
        store = preset_store(current_user)
        presets = await store.read()
        new_presets = [p for p in presets if p.get("id") != preset_id]
        if len(new_presets) == len(presets):
            return False
        await store.write(new_presets)
        return True

    @strawberry.mutation
    async def export_data(self, current_user: str) -> ExportDataResult:
        """导出当前用户全量文本数据."""
        u_dir = user_data_dir(current_user)
        files: dict[str, str] = {}
        if u_dir.exists():
            for fpath in u_dir.rglob("*"):
                if "memorybank" in fpath.parts:
                    continue  # 跳过 FAISS 二进制和内部元数据
                if fpath.is_file() and fpath.suffix in (".jsonl", ".toml", ".json"):
                    try:
                        content = fpath.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
                    rel = str(fpath.relative_to(u_dir))
                    files[rel] = content
        return ExportDataResult(files=cast("JSON", files))

    @strawberry.mutation
    async def delete_all_data(self, current_user: str) -> bool:
        """删除当前用户全量数据."""
        u_dir = user_data_dir(current_user)
        if not u_dir.exists():
            return False
        try:
            shutil.rmtree(u_dir)
        except OSError as e:
            logger.warning("Failed to delete user data: %s", e)
            return False
        return True

    # --- PendingReminder mutations（模块 2.3） ---

    @strawberry.mutation
    async def poll_pending_reminders(
        self,
        current_user: str = "default",
        context_input: DrivingContextInput | None = None,
    ) -> PollResult:
        """车机端轮询待触发提醒."""
        pm = PendingReminderManager(user_data_dir(current_user))
        ctx = input_to_context(context_input).model_dump() if context_input else {}
        triggered = await pm.poll(ctx)
        return PollResult(
            triggered=[
                TriggeredReminderGQL(
                    id=r["id"],
                    event_id=r.get("event_id", ""),
                    content=cast("JSON", r.get("content", {})),
                    triggered_at=datetime.now(UTC).isoformat(),
                )
                for r in triggered
            ]
        )

    @strawberry.mutation
    async def cancel_pending_reminder(
        self,
        reminder_id: str,
        current_user: str = "default",
    ) -> bool:
        """取消指定 ID 的待触发提醒."""
        pm = PendingReminderManager(user_data_dir(current_user))
        await pm.cancel(reminder_id)
        return True

    @strawberry.mutation
    async def get_pending_reminders(
        self,
        current_user: str = "default",
    ) -> list[PendingReminderGQL]:
        """获取当前用户所有待触发提醒列表."""
        pm = PendingReminderManager(user_data_dir(current_user))
        pending = await pm.list_pending()
        return [
            PendingReminderGQL(
                id=r["id"],
                event_id=r.get("event_id", ""),
                trigger_type=r.get("trigger_type", ""),
                trigger_text=r.get("trigger_text", ""),
                status=r.get("status", ""),
                created_at=r.get("created_at", ""),
            )
            for r in pending
        ]

    # --- 多轮对话（模块 4.3） ---

    @strawberry.mutation
    async def close_session(
        self,
        session_id: str,
        current_user: str = "default",  # 保留——Strawberry mutation 签名一致性
    ) -> bool:
        """关闭指定会话。"""
        _conversation_manager.close(session_id)
        return True
