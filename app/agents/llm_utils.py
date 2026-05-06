"""LLM 调用 → JSON 解析工具。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel


class LLMJsonClient:
    """LLM 调用 → JSON 解析。与 workflow._call_llm_json 等同行为。"""

    MARKDOWN_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)

    def __init__(self, chat_model: ChatModel) -> None:
        """初始化 LLMJsonClient。"""
        self._model = chat_model

    async def call(self, user_prompt: str) -> dict:
        """调用 LLM 生成 JSON。失败时回退为 {"raw": text}。"""
        raw = await self._model.generate(user_prompt)
        cleaned = self._extract_json(raw)
        return self._parse(cleaned, raw)

    def _extract_json(self, text: str) -> str:
        """提取 Markdown 代码块中的 JSON，无代码块则返回原文本。"""
        m = self.MARKDOWN_RE.search(text)
        if m:
            return m.group(1).strip()
        return text.strip()

    def _parse(self, cleaned: str, raw: str) -> dict:
        """解析 JSON 字符串，失败或非 dict 时回退。"""
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": raw}
        if not isinstance(parsed, dict):
            return {"raw": raw}
        parsed["raw"] = raw
        return parsed
