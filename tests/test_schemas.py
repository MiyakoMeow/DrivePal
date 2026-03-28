"""MemoryEvent, SearchResult, FeedbackData 模型测试."""

from app.memory.schemas import (
    MemoryEvent,
    SearchResult,
    FeedbackData,
    InteractionRecord,
)


class TestMemoryEvent:
    def test_default_fields(self):
        event = MemoryEvent(content="hello")
        assert event.content == "hello"
        assert event.id == ""
        assert event.type == "reminder"

    def test_extra_fields_allowed(self):
        event = MemoryEvent(content="hello", memory_strength=1, date_group="2026-01-01")
        assert event.memory_strength == 1
        assert event.date_group == "2026-01-01"

    def test_model_dump(self):
        event = MemoryEvent(id="abc", content="hello", type="reminder")
        d = event.model_dump()
        assert d == {
            "id": "abc",
            "created_at": "",
            "content": "hello",
            "type": "reminder",
            "description": "",
        }

    def test_from_dict(self):
        event = MemoryEvent(**{"id": "x", "content": "y", "created_at": "2026-01-01"})
        assert event.id == "x"


class TestSearchResult:
    def test_default_fields(self):
        sr = SearchResult(event={"content": "hello"})
        assert sr.score == 0.0
        assert sr.source == "event"
        assert sr.interactions == []

    def test_to_public_excludes_internal(self):
        sr = SearchResult(
            event={"content": "hello"},
            score=0.9,
            source="event",
            interactions=[{"q": "x"}],
        )
        pub = sr.to_public()
        assert "content" in pub
        assert "score" not in pub
        assert "source" not in pub

    def test_to_public_includes_interactions(self):
        sr = SearchResult(event={"content": "hello"}, interactions=[{"q": "x"}])
        pub = sr.to_public()
        assert pub["interactions"] == [{"q": "x"}]

    def test_to_public_no_interactions(self):
        sr = SearchResult(event={"content": "hello"})
        pub = sr.to_public()
        assert "interactions" not in pub


class TestFeedbackData:
    def test_extra_fields(self):
        fb = FeedbackData(action="accept", modified_content="new")
        assert fb.modified_content == "new"

    def test_model_dump(self):
        fb = FeedbackData(event_id="x", action="accept")
        d = fb.model_dump()
        assert d["event_id"] == "x"


class TestInteractionRecord:
    def test_default_fields(self):
        ir = InteractionRecord(id="x", query="q", response="r")
        assert ir.event_id == ""
        assert ir.memory_strength == 1
