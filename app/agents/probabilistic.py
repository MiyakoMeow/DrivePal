"""概率推断模块：意图不确定性 + 打断风险评估。"""

import logging
import os
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_WORKLOAD_MAP = {"low": 0.1, "normal": 0.3, "high": 0.6, "overloaded": 0.9}
_SCENARIO_MAP = {"parked": 0.0, "city_driving": 0.4, "traffic_jam": 0.3, "highway": 0.7}

_SPEED_THRESHOLD_40 = 40
_SPEED_THRESHOLD_80 = 80
OVERLOADED_WARNING_THRESHOLD = 0.36  # 公开常量，workflow.py 等共享
# 打断风险警告阈值（疲劳临界 ~0.7×0.4 + normal×0.3 + city×0.2 ≈ 0.45）


def _speed_factor(speed_kmh: float) -> float:
    if speed_kmh <= 0:
        return 0.0
    if speed_kmh <= _SPEED_THRESHOLD_40:
        return 0.3
    if speed_kmh <= _SPEED_THRESHOLD_80:
        return 0.5
    return 0.8


def is_enabled() -> bool:
    """检查概率推断是否启用（环境变量 PROBABILISTIC_INFERENCE_ENABLED，默认开启）。"""
    return os.environ.get("PROBABILISTIC_INFERENCE_ENABLED", "1") != "0"


async def infer_intent(
    query_text: str,
    memory_store: Any,  # noqa: ANN401
    user_id: str | None = None,
) -> dict:
    """从 MemoryBank 检索相似事件，聚合 type 得分推断意图。

    Args:
        query_text: 用户查询文本。
        memory_store: MemoryBankStore 实例（需实现 search(query, top_k) → list[SearchResult]）。
        user_id: 可选，传给 search() 的多用户隔离标识。

    Returns:
        {"intent_confidence": float, "alternative": str|None, "alt_confidence": float}
        冷启动时 confidence=0.2, alternative=None。

    """
    try:
        kwargs: dict[str, object] = {"top_k": 20}
        if user_id is not None:
            kwargs["user_id"] = user_id
        results = await memory_store.search(query_text, **kwargs)
    except (OSError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("Intent inference search failed: %s", e)
        results = []

    if not results:
        return {"intent_confidence": 0.2, "alternative": None, "alt_confidence": 0.0}

    type_scores: dict[str, float] = defaultdict(float)
    for r in results:
        event = r.event if hasattr(r, "event") else {}
        etype = (
            event.get("type", "general")
            if isinstance(event, dict)
            else getattr(event, "type", "general")
        )
        type_scores[etype] += max(r.score, 0.0)

    total = sum(type_scores.values()) or 1.0
    confidences = {t: s / total for t, s in type_scores.items()}
    sorted_types = sorted(confidences.items(), key=lambda x: x[1], reverse=True)

    return {
        "intent_confidence": sorted_types[0][1],
        "alternative": sorted_types[1][0] if len(sorted_types) > 1 else None,
        "alt_confidence": sorted_types[1][1] if len(sorted_types) > 1 else 0.0,
    }


_OVERLOADED_SCORE = 0.9


def compute_interrupt_risk(driving_context: dict) -> float:
    """根据驾车状态计算打断风险 0~1。

    公式: 0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed
    scenario 缺失时 risk=0.5（保守防御）。
    """
    driver = driving_context.get("driver", {})
    fatigue = float(driver.get("fatigue_level", 0.0))
    workload = driver.get("workload", "normal")
    scenario = driving_context.get("scenario")

    w_score = _WORKLOAD_MAP.get(workload, 0.3)
    s_risk = _SCENARIO_MAP.get(scenario, 0.5) if scenario else 0.5

    spatial = driving_context.get("spatial", {})
    loc = spatial.get("current_location", {}) if isinstance(spatial, dict) else {}
    speed = float(loc.get("speed_kmh", 0.0) or 0.0)
    sf = _speed_factor(speed)

    risk = 0.4 * fatigue + 0.3 * w_score + 0.2 * s_risk + 0.1 * sf

    if w_score >= _OVERLOADED_SCORE and risk >= OVERLOADED_WARNING_THRESHOLD:
        logger.info("High interrupt risk (%.2f) with overloaded workload", risk)

    return min(max(risk, 0.0), 1.0)
