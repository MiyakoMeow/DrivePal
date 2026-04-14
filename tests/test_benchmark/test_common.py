"""适配器通用工具测试."""

import pytest

from app.memory.schemas import (
    FeedbackData,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)
from benchmark.VehicleMemBench.strategies.common import (
    StoreClient,
    format_search_results,
    history_to_interaction_records,
)

SAMPLE_HISTORY = "[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3\n[2025-03-03 08:31] Justin Martinez: That sounds comfortable\n[2025-03-05 07:45] Gary Allen: When driving at night, I prefer the dashboard dim\n"

EXPECTED_RECORD_COUNT = 3
EXPECTED_SEARCH_COUNT = 2


def test_history_to_interaction_records() -> None:
    """测试将历史文本转换为交互记录."""
    records = history_to_interaction_records(SAMPLE_HISTORY)
    assert len(records) == EXPECTED_RECORD_COUNT
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
    """测试格式化带事件搜索结果包含元信息."""
    results = [
        SearchResult(
            event={
                "content": "Gary prefers seat heating level 3",
                "id": "1",
                "date_group": "2025-03-03",
                "memory_strength": 2,
                "last_recall_date": "2025-03-03",
            },
            score=0.9,
            source="event",
            interactions=[
                {"query": "seat heating level 3", "response": "Done"},
            ],
        ),
        SearchResult(
            event={
                "content": "Gary likes dashboard dim at night",
                "id": "2",
                "date_group": "2025-03-05",
                "memory_strength": 1,
                "last_recall_date": "2025-03-05",
            },
            score=0.8,
            source="event",
        ),
    ]
    text, count = format_search_results(results)
    assert count == EXPECTED_SEARCH_COUNT
    assert "Memory Result 1" in text
    assert "2025-03-03" in text
    assert "Strength: 2" in text
    assert "seat heating level 3" in text
    assert "Related interactions" in text
    assert "Memory Result 2" in text
    assert "2025-03-05" in text


@pytest.mark.asyncio
async def test_store_client_delegates_to_store() -> None:
    """测试 StoreClient 将搜索委托给 store."""

    class FakeStore:
        store_name = "fake"
        requires_embedding = False
        requires_chat = False
        supports_interaction = False

        async def write(self, _event: MemoryEvent) -> str:
            return "fake_id"

        async def search(self, query: str, **_kwargs: object) -> list[SearchResult]:
            return [SearchResult(event={"content": f"result for {query}"}, score=1.0)]

        async def get_history(self, _limit: int = 10) -> list[MemoryEvent]:
            return []

        async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
            pass

        async def write_interaction(
            self,
            _query: str,
            _response: str,
            _event_type: str = "reminder",
        ) -> InteractionResult:
            return InteractionResult(
                event_id="fake_event_id", interaction_id="fake_interaction_id"
            )

    client = StoreClient(FakeStore())  # ty: ignore[invalid-argument-type]
    results = await client.search(query="test", top_k=5)
    assert len(results) == 1
