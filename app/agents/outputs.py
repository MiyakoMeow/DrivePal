"""多格式输出路由 + 通道 + 打断级别."""

from dataclasses import dataclass
from enum import Enum


class OutputChannel(Enum):
    """输出通道枚举。统一 rules.py / prompts / API 中的通道字符串."""

    AUDIO = "audio"
    VISUAL = "visual"
    DETAILED = "detailed"


class InterruptLevel(Enum):
    """打断级别枚举。替代原有 only_urgent 二元决策."""

    NORMAL = 0  # 不打断
    URGENT_NORMAL = 1  # 紧急，可缓3s
    URGENT_IMMEDIATE = 2  # 立即打断，ducking


@dataclass
class MultiFormatContent:
    """多格式提醒内容。

    与 workflow.py 中的 ReminderContent (Pydantic, 用于内容提取) 区分——
    此类为输出路由的最终结果类型，供 SSE / API 返回。
    """

    speakable_text: str  # ≤15字，无标点，TTS 友好
    display_text: str  # ≤20字，HUD 可扫读
    detailed: str  # 完整文本
    channel: OutputChannel  # 目标输出通道
    interrupt_level: InterruptLevel  # 打断级别

    def model_dump(self) -> dict:
        """将 MultiFormatContent 序列化为 JSON 友好的 dict。"""
        return {
            "speakable_text": self.speakable_text,
            "display_text": self.display_text,
            "detailed": self.detailed,
            "channel": self.channel.value,
            "interrupt_level": self.interrupt_level.value,
        }


class OutputRouter:
    """决策 → MultiFormatContent 路由。

    处理 speakable_text/display_text fallback 和通道/打断级别决策。
    """

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        t = str(text).strip("。！？,.!? \t\n")
        return t[:max_len] if t else "提醒"

    @staticmethod
    def _compute_channel(rules_result: dict) -> OutputChannel:
        allowed = rules_result.get("allowed_channels", [])
        if allowed:
            first = allowed[0]
            if isinstance(first, OutputChannel):
                return first
            try:
                return OutputChannel(first)
            except ValueError:
                pass
        return OutputChannel.VISUAL

    @staticmethod
    def _compute_interrupt_level(decision: dict, rules_result: dict) -> InterruptLevel:
        if decision.get("is_emergency"):
            return InterruptLevel.URGENT_IMMEDIATE
        if rules_result.get("only_urgent"):
            return InterruptLevel.URGENT_NORMAL
        return InterruptLevel.NORMAL

    def route(
        self,
        decision: dict,
        scenario: str,  # 预留，后续 scenario-aware 路由使用
        rules_result: dict,
    ) -> MultiFormatContent:
        """将 LLM 决策路由为 MultiFormatContent。

        Args:
            decision: Strategy Agent 输出的决策 dict。
            scenario: 驾驶场景字符串（预留，未来用于场景感知路由）。
            rules_result: 规则引擎 apply_rules() 的输出。

        """
        rc = decision.get("reminder_content", {})
        if isinstance(rc, str):
            rc = {"detailed": rc}

        detailed = rc.get("detailed", "") or ""

        speakable = rc.get("speakable_text", "")
        if not speakable:
            speakable = self._truncate(str(detailed), 15)

        display = rc.get("display_text", "")
        if not display:
            display = self._truncate(str(detailed), 20)

        return MultiFormatContent(
            speakable_text=str(speakable),
            display_text=str(display),
            detailed=str(detailed),
            channel=self._compute_channel(rules_result),
            interrupt_level=self._compute_interrupt_level(decision, rules_result),
        )
