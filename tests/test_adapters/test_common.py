from adapters.memory_adapters.common import (
    history_to_interaction_records,
    format_search_results,
    StoreClient,
)


SAMPLE_HISTORY = "[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3\n[2025-03-03 08:31] Justin Martinez: That sounds comfortable\n[2025-03-05 07:45] Gary Allen: When driving at night, I prefer the dashboard dim\n"


def test_history_to_interaction_records():
    records = history_to_interaction_records(SAMPLE_HISTORY)
    assert len(records) == 3
    assert records[0].content == "Gary Allen: I like the seat heating on level 3"
    assert records[0].date_group == "2025-03-03"
    assert records[1].date_group == "2025-03-03"
    assert records[2].date_group == "2025-03-05"


def test_history_to_interaction_records_empty():
    records = history_to_interaction_records("")
    assert records == []


def test_format_search_results_empty():
    text, count = format_search_results([])
    assert text == ""
    assert count == 0


def test_format_search_results_with_events():
    from app.memory.schemas import SearchResult

    results = [
        SearchResult(
            event={"content": "Gary prefers seat heating level 3", "id": "1"}, score=0.9
        ),
        SearchResult(
            event={"content": "Gary likes dashboard dim at night", "id": "2"}, score=0.8
        ),
    ]
    text, count = format_search_results(results)
    assert count == 2
    assert "seat heating" in text
    assert "dashboard dim" in text


def test_store_client_delegates_to_store():
    class FakeStore:
        def search(self, query, top_k=10):
            return [
                type(
                    "R", (), {"event": {"content": f"result for {query}"}, "score": 1.0}
                )
            ]

    client = StoreClient(FakeStore())
    results = client.search(query="test", top_k=5)
    assert len(results) == 1
