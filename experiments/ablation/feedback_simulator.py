"""反馈模拟与权重更新——从 personalization_group 提取."""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import random

from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)

_SIMULATED_ACCEPT_PROB = 0.5

_KNOWN_TASK_TYPES: frozenset[str] = frozenset(
    {"meeting", "travel", "shopping", "contact", "other"}
)


def simulate_feedback(
    decision: dict,
    stage: str,
    rng: random.Random,
    *,
    stages: dict | None = None,
    scenario_id: str = "",
) -> Literal["accept", "ignore"]:
    """模拟用户反馈——根据阶段偏好决定 accept 或 ignore。

    设计动机：
    - 直接操作 strategies.toml 的 reminder_weights 而非走正式 submitFeedback
      mutation，因为反馈模拟需要同步、确定性的权重更新以复现实验；走全套
      GraphQL API（写 feedback.jsonl + 更新 memory_strength）引入不必要的
      异步依赖和竞态风险。
    - visual-detail 阶段优先从 stages["decision"]（规则引擎前的 LLM 原始
      输出）读取意图，因为规则引擎可能因安全约束修改 reminder_content，导致
      has_visual_content 误判。stages["visual-detail"] 是 LLM 在未受硬约束
      干扰下的真实意图。
    - _KNOWN_TASK_TYPES 仅接受 meeting/travel/shopping/contact/other——
      LLM 有时输出非标准 task_type（如 "navigation"/"reminder"），这些值
      无法映射到权重维度，接受后将污染提醒策略。

    Args:
        decision: 最终决策 dict（可能已被规则引擎修改）。
        stage: 当前实验阶段名。
        rng: 随机数生成器。
        stages: AgentWorkflow 各阶段原始输出。visual-detail 阶段优先从此读取
            LLM 原始意图（规则引擎前的 reminder_content）。
        scenario_id: 场景标识，用于诊断日志。

    """
    if stage == "high-freq":
        return "accept" if decision.get("should_remind") else "ignore"
    if stage == "silent":
        return (
            "accept"
            if decision.get("should_remind") and decision.get("is_emergency")
            else "ignore"
        )
    if stage == "visual-detail":
        if stages and stages.get("decision") == decision:
            logger.debug(
                "规则引擎未修改 decision，反馈基于原始 LLM 输出 (scenario: %s)",
                scenario_id,
            )
        return "accept" if has_visual_content(decision, stages=stages) else "ignore"
    if stage == "mixed":
        return "accept" if rng.random() < _SIMULATED_ACCEPT_PROB else "ignore"
    return "ignore"


def has_visual_content(decision: dict, *, stages: dict | None = None) -> bool:
    """判断 LLM 是否意图生成视觉内容。

    优先从 stages["decision"]（规则引擎前的 LLM 原始输出）读取，
    stages 无数据时 fallback 到 decision（可能已被规则引擎修改）。
    """
    source = decision
    if stages:
        stage_decision = stages.get("decision")
        if isinstance(stage_decision, dict) and isinstance(
            stage_decision.get("reminder_content"), dict
        ):
            source = stage_decision
    rc = source.get("reminder_content")
    if not isinstance(rc, dict):
        return False
    display = rc.get("display_text")
    detailed = rc.get("detailed")
    return bool(
        (isinstance(display, str) and display.strip())
        or (isinstance(detailed, str) and detailed.strip())
    )


def extract_task_type(stages: dict) -> str | None:
    """从 stages.task 提取任务类型。

    LLM 输出的 key 名不一致——可能为 task_type / task_attribution。
    仅接受已知类型（_KNOWN_TASK_TYPES），过滤如 "navigation"/"reminder" 等
    非标准值——这些值无法映射到 reminder_weights 的维度，接受后权重更新
    将绑定错误 key。
    """
    task_stage = stages.get("task", {})
    if isinstance(task_stage, dict):
        for key in ("task_type", "task_attribution"):
            val = task_stage.get(key)
            if isinstance(val, str) and val.strip():
                stripped = val.strip()
                if stripped in _KNOWN_TASK_TYPES:
                    return stripped
                logger.debug("task_type=%r 不在已知类型集合中，跳过反馈", stripped)
    return None


def _safe_read_weights(current: Any) -> dict[str, float]:
    """从 TOML 读取结果中安全提取 reminder_weights。

    配置损坏（值非 Mapping、key 非 str、value 非数字）时返回空 dict，
    避免后续计算因脏类型抛异常。
    """
    if not isinstance(current, MutableMapping):
        return {}
    raw = current.get("reminder_weights")
    if not isinstance(raw, Mapping):
        return {}
    clean: dict[str, float] = {}
    for key, val in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(val, (int, float)):
            clean[key] = float(val)
    return clean


async def update_feedback_weight(
    user_id: str,
    event_id: str | None,
    action: Literal["accept", "ignore"],
    *,
    task_type: str | None = None,
) -> None:
    """模拟反馈写入 strategies.toml，更新 reminder_weights。

    优先使用显式传入的 task_type；否则回退 MemoryBank 查询。
    """
    event_type = task_type
    if not event_type:
        logger.debug(
            "task_type 未从 stages 提取（event_id=%s），回退 MemoryBank 查询", event_id
        )
        if event_id:
            mm = get_memory_module()
            mode = MemoryMode.MEMORY_BANK
            event_type = await mm.get_event_type(event_id, mode=mode, user_id=user_id)
    if not event_type:
        return
    ud = user_data_dir(user_id)
    strategy_store = TOMLStore(
        user_dir=ud, filename="strategies.toml", default_factory=dict
    )
    current = await strategy_store.read()
    weights = _safe_read_weights(current)
    delta = 0.1 if action == "accept" else -0.1
    weights[event_type] = max(0.1, min(1.0, weights.get(event_type, 0.5) + delta))
    await strategy_store.update("reminder_weights", weights)


async def read_weights(user_id: str) -> dict[str, float]:
    """读取用户的 reminder_weights 配置（经类型校验清洗）。"""
    ud = user_data_dir(user_id)
    store = TOMLStore(user_dir=ud, filename="strategies.toml", default_factory=dict)
    current = await store.read()
    return _safe_read_weights(current)
