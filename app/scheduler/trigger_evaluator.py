"""评估各路触发信号。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.agents.rules import apply_rules

_HIGH_PRIORITY = 2


@dataclass
class TriggerSignal:
    """触发信号：描述一次触发事件的来源、优先级和上下文。"""

    source: str  # "context_change"|"location"|"time"|"state"|"periodic"|"voice"
    priority: int  # 0=low, 1=normal, 2=high
    context: dict | None = None
    memory_hints: list[dict] | None = None


@dataclass
class TriggerDecision:
    """触发决策：是否触发及原因。"""

    should_trigger: bool = False
    reason: str = ""
    interrupt_level: int = 0


class TriggerEvaluator:
    """评估各路触发信号，应用去抖和驾驶约束。"""

    def __init__(self, debounce_seconds: float = 30.0) -> None:
        """初始化 TriggerEvaluator。

        Args:
            debounce_seconds: 同一来源的最小触发间隔（秒）。

        """
        self._debounce_seconds = debounce_seconds
        self._last_trigger_time: dict[str, float] = {}

    def evaluate(
        self, signal: TriggerSignal, driving_context: dict | None
    ) -> TriggerDecision:
        """评估触发信号，返回是否触发及原因。"""
        now = time.time()
        last = self._last_trigger_time.get(signal.source, 0)
        if now - last < self._debounce_seconds:
            return TriggerDecision(
                should_trigger=False, reason=f"去抖：{signal.source}"
            )

        if driving_context:
            constraints = apply_rules(driving_context)
            if constraints.get("only_urgent") and signal.priority < _HIGH_PRIORITY:
                return TriggerDecision(should_trigger=False, reason="仅紧急可发送")
            if constraints.get("postpone") and signal.priority < _HIGH_PRIORITY:
                return TriggerDecision(should_trigger=False, reason="非紧急应延后")

        self._last_trigger_time[signal.source] = now
        return TriggerDecision(
            should_trigger=True,
            reason=f"{signal.source} 触发",
            interrupt_level=signal.priority,
        )
