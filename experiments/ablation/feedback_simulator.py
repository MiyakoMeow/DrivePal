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

from ._io import get_fatigue_threshold

logger = logging.getLogger(__name__)


def _get_fatigue(driving_context: dict | None) -> float:
    if not isinstance(driving_context, dict):
        return 0.5
    driver = driving_context.get("driver", {})
    if not isinstance(driver, dict):
        return 0.5
    fatigue = driver.get("fatigue_level", 0.5)
    return float(fatigue) if isinstance(fatigue, (int, float)) else 0.5


def _get_workload(driving_context: dict | None) -> str:
    if not isinstance(driving_context, dict):
        return "normal"
    driver = driving_context.get("driver", {})
    if not isinstance(driver, dict):
        return "normal"
    wl = driver.get("workload", "normal")
    return str(wl) if isinstance(wl, str) else "normal"


def _compute_alignment(decision: dict, stage: str) -> float:
    """决策与阶段偏好的对齐度 [0,1]。

    high-freq/visual-detail: 二值 1.0/0.0
    silent: 二值 1.0/0.0（含 emergency 豁免）
    mixed: 偏置 0.6/0.4——不再固定 0.5 使 mixed 也能 resolve 为 accept/reject
    """
    if stage == "mixed":
        return 0.6 if decision.get("should_remind") else 0.4
    if stage == "high-freq":
        return 1.0 if decision.get("should_remind") else 0.0
    if stage == "silent":
        if not decision.get("should_remind"):
            return 1.0
        return 1.0 if decision.get("is_emergency") else 0.0
    if stage == "visual-detail":
        return 1.0 if has_visual_content(decision) else 0.0
    return 0.5


_KNOWN_TASK_TYPES: frozenset[str] = frozenset(
    {"meeting", "travel", "shopping", "contact", "other"}
)

_current_delta: dict[tuple[str, str], float] = {}
"""按 (user_id, task_type) 追踪当前步长。串行调用安全（personalization_group 串行）。"""

_recent_feedback: dict[tuple[str, str], list[int]] = {}
"""按 (user_id, task_type) 追踪最近 3 次反馈方向。+1=accept, -1=ignore。"""


def _adaptive_delta(user_id: str, task_type: str, action: str) -> float:
    """自适应步长。同向加速（×1.5），反向减速（×0.5），clamp [0.05, 0.3]。

    状态按 (user_id, task_type) 隔离，避免跨用户反馈历史污染。
    """
    key = (user_id, task_type)
    delta = _current_delta.get(key, 0.1)
    history = _recent_feedback.setdefault(key, [])
    direction = 1 if action == "accept" else -1
    history.append(direction)
    if len(history) > 3:
        history.pop(0)
    if len(history) < 3:
        _current_delta[key] = 0.1
        return 0.1
    if all(d == direction for d in history):
        delta = min(0.3, delta * 1.5)
    else:
        delta = max(0.05, delta * 0.5)
    _current_delta[key] = delta
    return delta


def simulate_feedback(
    decision: dict,
    stage: str,
    rng: random.Random,
    *,
    _scenario_id: str = "",
    driving_context: dict | None = None,
) -> Literal["accept", "ignore"] | None:
    """模拟用户反馈——三要素模型。

    1. 对齐度 (alignment): 决策与阶段偏好的匹配度 [0,1]
    2. 噪声 (noise): 用户偶发误反馈概率 = 0.1 + fatigue * 0.2, 范围 [0.1, 0.3]
    3. 反馈概率 (fb_prob): 用户实际给出反馈的概率 = 0.8 - penalty(workload, fatigue), 范围 [0.3, 0.8]
    """
    alignment = _compute_alignment(decision, stage)
    fatigue = _get_fatigue(driving_context)
    workload = _get_workload(driving_context)

    noise = 0.1 + fatigue * 0.2
    fb_prob = 0.8
    if workload == "overloaded":
        fb_prob -= 0.1
    if fatigue > get_fatigue_threshold():
        fb_prob -= 0.1
    fb_prob = max(0.3, fb_prob)

    if rng.random() > fb_prob:
        return None
    if rng.random() < noise:
        return "accept" if rng.random() < 0.5 else "ignore"
    return "accept" if alignment > 0.5 else "ignore"


def has_visual_content(decision: dict) -> bool:
    """判断 LLM 是否意图生成视觉内容。

    postprocess_decision 仅修改 should_remind/allowed_channels/清空 reminder_content，
    不修改 reminder_content 子字段（display_text / detailed）。
    stages 优先逻辑已移除——execution_agent 同步 stages.decision 后两者恒等同。
    """
    rc = decision.get("reminder_content")
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

    LLM 输出的 key 名不一致——可能为 type / task_type / task_attribution。
    仅接受已知类型（_KNOWN_TASK_TYPES），过滤如 "navigation"/"reminder" 等
    非标准值——这些值无法映射到 reminder_weights 的维度，接受后权重更新
    将绑定错误 key。
    """
    task_stage = stages.get("task", {})
    if isinstance(task_stage, dict):
        for key in ("type", "task_type", "task_attribution"):
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
        logger.warning(
            "update_feedback_weight(%s): 无 task_type 且无 event_id，跳过权重更新。"
            "调用方应在调用前保证至少其一可用。",
            user_id,
        )
        return
    ud = user_data_dir(user_id)
    strategy_store = TOMLStore(
        user_dir=ud, filename="strategies.toml", default_factory=dict
    )
    current = await strategy_store.read()
    weights = _safe_read_weights(current)
    if task_type:
        delta = _adaptive_delta(user_id, task_type, action)
        if action == "ignore":
            delta = -delta
    else:
        delta = 0.1 if action == "accept" else -0.1
    weights[event_type] = max(0.1, min(1.0, weights.get(event_type, 0.5) + delta))
    await strategy_store.update("reminder_weights", weights)


async def read_weights(user_id: str) -> dict[str, float]:
    """读取用户的 reminder_weights 配置（经类型校验清洗）。"""
    ud = user_data_dir(user_id)
    store = TOMLStore(user_dir=ud, filename="strategies.toml", default_factory=dict)
    current = await store.read()
    return _safe_read_weights(current)


def export_state() -> dict:
    """导出当前反馈状态以备持久化。

    Returns:
        {"_current_delta": {...}, "_recent_feedback": {...}}
        键为 "user_id::task_type" 格式的字符串（dict key 可序列化）。

    """
    return {
        "_current_delta": {
            f"{uid}::{tt}": v for (uid, tt), v in _current_delta.items()
        },
        "_recent_feedback": {
            f"{uid}::{tt}": list(v) for (uid, tt), v in _recent_feedback.items()
        },
    }


def restore_state(state: dict) -> None:
    """从持久化状态恢复反馈状态。幂等——清空后写入。"""
    _current_delta.clear()
    _recent_feedback.clear()
    for key_str, val in state.get("_current_delta", {}).items():
        if "::" in key_str:
            uid, tt = key_str.split("::", 1)
            _current_delta[(uid, tt)] = float(val)
    for key_str, val in state.get("_recent_feedback", {}).items():
        if "::" in key_str:
            uid, tt = key_str.split("::", 1)
            _recent_feedback[(uid, tt)] = [
                int(v) for v in val if isinstance(v, (int, float))
            ]
