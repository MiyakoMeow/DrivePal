"""快捷指令解析器——高频场景不走 LLM 流水线."""

import logging
import tomllib
from pathlib import Path

from app.agents.pending import parse_duration, parse_time

logger = logging.getLogger(__name__)

_SHORTCUTS_PATH = Path(__file__).resolve().parents[2] / "config" / "shortcuts.toml"


class ShortcutResolver:
    """加载 shortcuts.toml 并匹配用户输入."""

    def __init__(self) -> None:
        """加载 shortcuts.toml 并初始化匹配器."""
        self._shortcuts: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            with _SHORTCUTS_PATH.open("rb") as f:
                data = tomllib.load(f)
            self._shortcuts = data.get("shortcuts", [])
        except OSError, tomllib.TOMLDecodeError:
            self._shortcuts = []

    def resolve(self, query: str) -> dict | None:
        """匹配查询返回预构建 decision dict，未命中返回 None."""
        candidates: list[tuple[int, int, dict, str]] = [
            (len(pat), sc.get("priority", 0), sc, query[len(pat) :].strip())
            for sc in self._shortcuts
            for pat in sc.get("patterns", [])
            if query == pat or query.startswith(pat)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[0], -x[1]))
        _, _, sc, params = candidates[0]
        return self._to_decision(sc, params)

    @staticmethod
    def _to_decision(shortcut: dict, params: str) -> dict:
        sc_type = shortcut.get("type", "")
        if sc_type == "travel":
            decision: dict = {
                "should_remind": True,
                "timing": "location",
                "type": "travel",
                "location": shortcut.get("location", ""),
                "reminder_content": {
                    "speakable_text": shortcut.get("speakable_text", ""),
                    "display_text": shortcut.get("display_text", ""),
                    "detailed": f"提醒：到达{shortcut.get('location', '')}时",
                },
            }
            if params:
                parsed_time = parse_time(params)
                if parsed_time:
                    decision["timing"] = "location_time"
                    decision["target_time"] = parsed_time
            return decision
        if sc_type == "action":
            action = shortcut.get("action", "")
            if action == "cancel_last":
                return {
                    "should_remind": False,
                    "timing": "skip",
                    "action": "cancel_last",
                }
            if action == "snooze":
                parsed = parse_duration(params) if params else None
                secs = parsed if parsed is not None else 300
                return {
                    "should_remind": True,
                    "timing": "delay",
                    "action": "snooze",
                    "delay_seconds": secs,
                    "type": "other",
                    "reminder_content": {
                        "speakable_text": shortcut.get("speakable_text", ""),
                        "display_text": shortcut.get("display_text", ""),
                        "detailed": f"已延迟{secs // 60}分钟",
                    },
                }
        logger.warning("Unknown shortcut type '%s', falling back to now", sc_type)
        return {"should_remind": True, "timing": "now"}
