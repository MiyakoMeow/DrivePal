"""记忆模块，实现关键词、LLM、向量和记忆库四种检索模式."""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional
from app.memory.memory_bank import MemoryBankBackend
from app.memory.utils import cosine_similarity
from app.storage.json_store import JSONStore
from app.models.embedding import EmbeddingModel
from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

LLM_SEARCH_PROMPT = """你是一个语义相关性判断助手。

判断用户的查询与给定的事件描述是否语义相关。

查询: {query}

事件: {event_description}

请返回JSON格式:
{{"relevant": true/false, "reasoning": "简短原因"}}
"""


class MemoryModule:

    """统一记忆管理接口，支持多种检索模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ):
        """初始化记忆模块."""
        self.data_dir = data_dir
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)
        self._memorybank_backend: Optional[MemoryBankBackend] = None

    def write(self, event: dict) -> str:
        """写入事件，返回event_id."""
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str, mode: str = "keyword") -> list:
        """检索记忆."""
        if mode == "keyword":
            return self._search_by_keyword(query)
        elif mode == "llm_only":
            return self._search_by_llm(query)
        elif mode == "embeddings":
            return self._search_by_embeddings(query)
        elif mode == "memorybank":
            return self._search_by_memorybank(query)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _search_by_keyword(self, query: str) -> list:
        """关键词匹配检索."""
        events = self.events_store.read()
        query_lower = query.lower()
        return [
            event
            for event in events
            if query_lower in event.get("content", "").lower()
            or query_lower in event.get("description", "").lower()
        ]

    def _search_by_llm(self, query: str) -> list:
        """使用LLM进行语义检索."""
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
                        results.append(event)
            except Exception as e:
                logger.warning("LLM relevance check failed: %s", e, exc_info=True)
                continue

        return results

    def _search_by_embeddings(self, query: str) -> list:
        """向量相似度检索."""
        if self.embedding_model is None:
            return self._search_by_keyword(query)

        query_vector = self.embedding_model.encode(query)
        events = self.events_store.read()
        if not events:
            return []

        event_texts = [event.get("content", "") for event in events]
        all_embeddings = self.embedding_model.batch_encode(event_texts)

        results = []
        for event, event_vector in zip(events, all_embeddings):
            similarity = cosine_similarity(query_vector, event_vector)
            if similarity > 0.7:
                results.append(event)

        return results

    def _get_memorybank_backend(self) -> MemoryBankBackend:
        if self._memorybank_backend is None:
            self._memorybank_backend = MemoryBankBackend(
                self.data_dir,
                embedding_model=self.embedding_model,
                chat_model=self.chat_model,
            )
        return self._memorybank_backend

    def write_interaction(self, query: str, response: str) -> str:
        """写入交互记录并返回交互ID."""
        backend = self._get_memorybank_backend()
        return backend.write_interaction(query, response)

    def _search_by_memorybank(self, query: str) -> list:
        backend = self._get_memorybank_backend()
        return backend.search(query)

    def get_history(self, limit: int = 10) -> list:
        """获取历史记录."""
        if limit < 0:
            raise ValueError(f"limit must be non-negative, got {limit}")
        events = self.events_store.read()
        return events[-limit:] if limit > 0 else []

    def update_feedback(self, event_id: str, feedback: dict):
        """更新反馈."""
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback["event_id"] = event_id
        feedback["timestamp"] = datetime.now().isoformat()
        feedback_store.append(feedback)

        self._update_strategy(event_id, feedback)

    def _update_strategy(self, event_id: str, feedback: dict):
        """根据反馈更新策略."""
        strategies = self.strategies_store.read()
        action = feedback.get("action")
        event_type = feedback.get("type", "default")

        if "reminder_weights" not in strategies:
            strategies["reminder_weights"] = {}

        if action == "accept":
            strategies["reminder_weights"][event_type] = min(
                strategies["reminder_weights"].get(event_type, 0.5) + 0.1, 1.0
            )
        elif action == "ignore":
            strategies["reminder_weights"][event_type] = max(
                strategies["reminder_weights"].get(event_type, 0.5) - 0.1, 0.1
            )

        self.strategies_store.write(strategies)
