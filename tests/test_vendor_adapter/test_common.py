"""适配器通用工具测试."""

import pytest

from vendor_adapter.VehicleMemBench.memory_adapters.common import (
    StoreClient,
    format_search_results,
    history_to_interaction_records,
)

SAMPLE_HISTORY = "[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3\n[2025-03-03 08:31] Justin Martinez: That sounds comfortable\n[2025-03-05 07:45] Gary Allen: When driving at night, I prefer the dashboard dim\n"


def test_history_to_interaction_records() -> None:
    """测试将历史文本转换为交互记录."""
    records = history_to_interaction_records(SAMPLE_HISTORY)
    assert len(records) == 3
    assert records[0].content == "Gary Allen: I like the seat heating on level 3"
    assert records[0].date_group == "2025-03-03"
    assert records[1].date_group == "2025-03-03"
    assert records[2].date_group == "2025-03-05"


def test_history_to_interaction_records_empty() -> None:
    """测试空历史返回空列表."""
    records = history_to_interaction_records("")
    assert records == []


def test_format_search_results_empty() -> None:
    """测试格式化空结果."""
    text, count = format_search_results([])
    assert text == ""
    assert count == 0


def test_format_search_results_with_events() -> None:
    """测试格式化带事件搜索结果."""
    from app.memory.schemas import SearchResult

    results = [
        SearchResult(
            event={"content": "Gary prefers seat heating level 3", "id": "1"},
            score=0.9,
        ),
        SearchResult(
            event={"content": "Gary likes dashboard dim at night", "id": "2"},
            score=0.8,
        ),
    ]
    text, count = format_search_results(results)
    assert count == 2
    assert "seat heating" in text
    assert "dashboard dim" in text


@pytest.mark.asyncio
async def test_store_client_delegates_to_store() -> None:
    """测试 StoreClient 将搜索委托给 store."""
    from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult

    class FakeStore:
        store_name = "fake"
        requires_embedding = False
        requires_chat = False
        supports_interaction = False

        async def write(self, event: MemoryEvent) -> str:
            return "fake_id"

        async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
            return [SearchResult(event={"content": f"result for {query}"}, score=1.0)]

        async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
            return []

        async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
            pass

        async def write_interaction(
            self,
            query: str,
            response: str,
            event_type: str = "reminder",
        ) -> str:
            return "fake_interaction_id"

    client = StoreClient(FakeStore())
    results = await client.search(query="test", top_k=5)
    assert len(results) == 1
