"""LLM 语义判断检索 store."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.models.chat import ChatModel
from app.models.embedding import EmbeddingModel
from app.storage.json_store import JSONStore

logger = logging.getLogger(__name__)

LLM_SEARCH_PROMPT = """你是一个语义相关性判断助手。

判断用户的查询与给定的事件描述是否语义相关。

查询: {query}

事件: {event_description}

请返回JSON格式:
{{"relevant": true/false, "reasoning": "简短原因"}}
"""


class LLMOnlyMemoryStore:
    """LLM 语义判断检索 store."""

    store_name = "llm_only"
    requires_embedding = False
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
        **kwargs: dict,
    ) -> None:
        """初始化 LLM 存储."""
        self._storage = EventStorage(data_dir)
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)
        self.chat_model = chat_model

    @property
    def events_store(self) -> JSONStore:
        """事件存储."""
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        """策略存储."""
        return self._feedback._strategies_store

    def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        return self._storage.append_event(event)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """LLM 语义搜索."""
        if not self.chat_model:
            return []

        events = self._storage.read_events()
        if not events:
            return []

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        results = []
        for event in events:
            event_text = event.get("content", "") or event.get("description", "")
            prompt = f"当前时间：{now}\n\n" + LLM_SEARCH_PROMPT.format(
                query=query, event_description=event_text
            )

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

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        return self._interaction.write_interaction(query, response, event_type)
