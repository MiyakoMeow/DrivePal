"""LLM 语义判断检索 store."""

import uuid
import json
import re
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

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
    """LLM 语义判断检索 store."""

    requires_chat: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model: Optional["ChatModel"] = None,
    ):
        """初始化 LLMOnlyMemoryStore 实例.

        Args:
            data_dir: 数据存储目录路径.
            embedding_model: 未使用，为兼容工厂签名.
            chat_model: LLM 模型实例.

        """
        super().__init__(data_dir)
        self.chat_model = chat_model

    @property
    def store_name(self) -> str:
        """返回 store 名称."""
        return "llm_only"

    def write(self, event: dict) -> str:
        """写入事件到 store.

        Args:
            event: 事件数据字典.

        Returns:
            事件 ID.

        """
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
        """使用 LLM 判断语义相关性进行搜索.

        Args:
            query: 搜索查询.

        Returns:
            匹配的事件列表.

        """
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
