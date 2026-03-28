"""LLM 语义判断检索 store."""

import json
import logging
import re
from typing import Optional, TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.base import BaseMemoryStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

LLM_SEARCH_PROMPT = """你是一个语义相关性判断助手。

判断用户的查询与给定的事件描述是否语义相关。

查询: {query}

事件: {event_description}

请返回JSON格式:
{{"relevant": true/false, "reasoning": "简短原因"}}
"""


class LLMOnlyMemoryStore(BaseMemoryStore):
    requires_chat: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model: Optional["ChatModel"] = None,
    ):
        super().__init__(data_dir)
        self.chat_model = chat_model

    @property
    def store_name(self) -> str:
        return "llm_only"

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if not self.chat_model:
            return []

        events = self.events_store.read()
        if not events:
            return []

        results = []
        for event in events:
            event_text = event.get("content", "") or event.get("description", "")
            prompt = LLM_SEARCH_PROMPT.format(query=query, event_description=event_text)

            try:
                response = self.chat_model.generate(prompt)
                json_match = re.search(r"\{.*?\}", response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if data.get("relevant"):
                        results.append(SearchResult(event=dict(event)))
            except Exception as e:
                logger.warning("LLM relevance check failed: %s", e, exc_info=True)
                continue

        return results[:top_k]
