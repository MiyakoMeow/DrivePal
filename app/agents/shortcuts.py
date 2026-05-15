"""快捷指令解析器——高频场景不走 LLM 流水线."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.agents.pending import parse_duration, parse_time
from app.config import ensure_config, get_config_root

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SHORTCUTS_TOML_DEFAULTS: dict = {
    "shortcuts": [
        {
            "patterns": ["提醒到家", "到家提醒", "到家叫我"],
            "type": "travel",
            "location": "home",
            "speakable_text": "到家提醒已设",
            "display_text": "到家提醒 · 已设",
            "priority": 10,
        },
        {
            "patterns": ["提醒到公司", "到公司提醒", "公司提醒"],
            "type": "travel",
            "location": "office",
            "speakable_text": "公司提醒已设",
            "display_text": "公司提醒 · 已设",
            "priority": 9,
        },
        {
            "patterns": ["取消提醒"],
            "type": "action",
            "action": "cancel_last",
            "speakable_text": "提醒已取消",
            "display_text": "已取消",
            "priority": 8,
        },
        {
            "patterns": ["延迟"],
            "type": "action",
            "action": "snooze",
            "speakable_text": "已延迟",
            "display_text": "已延迟",
            "priority": 5,
        },
    ],
}

_SHORTCUTS_PATH: Path = get_config_root() / "shortcuts.toml"


class ShortcutResolver:
    """加载 shortcuts.toml 并匹配用户输入."""

    def __init__(self) -> None:
        """加载 shortcuts.toml 并初始化匹配器。"""
        self._shortcuts: list[dict] = []
        self._load()

    def _load(self) -> None:
        """加载快捷键配置。ensure_config 内部全 catch，不抛 I/O 异常。"""
        data = ensure_config(_SHORTCUTS_PATH, _SHORTCUTS_TOML_DEFAULTS)
        self._shortcuts = data.get("shortcuts", [])

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
                    decision["target_time"] = parsed_time.isoformat()
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
