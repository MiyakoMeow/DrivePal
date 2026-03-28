"""MemoryEvent, SearchResult, FeedbackData 模型测试."""

from app.memory.schemas import (
    MemoryEvent,
    SearchResult,
    FeedbackData,
    InteractionRecord,
)


class TestMemoryEvent:
    """MemoryEvent 模型测试."""

    def test_default_fields(self):
        """验证默认字段值."""
        event = MemoryEvent(content="hello")
        assert event.content == "hello"
        assert event.id == ""
        assert event.type == "reminder"

    def test_extra_fields_allowed(self):
        """验证 extra='allow' 允许未知字段."""
        event = MemoryEvent(content="hello")
        setattr(event, "custom_field", "value")
        assert getattr(event, "custom_field") == "value"

    def test_model_dump(self):
        """验证 model_dump 序列化输出."""
        event = MemoryEvent(id="abc", content="hello", type="reminder")
        d = event.model_dump()
        assert d == {
            "id": "abc",
            "created_at": "",
            "content": "hello",
            "type": "reminder",
            "description": "",
            "memory_strength": 0,
            "last_recall_date": "",
            "date_group": "",
            "interaction_ids": [],
            "updated_at": "",
        }

    def test_from_dict(self):
        """验证从字典构造."""
        event = MemoryEvent(id="x", content="y", created_at="2026-01-01")
        assert event.id == "x"


class TestSearchResult:
    """SearchResult 模型测试."""

    def test_default_fields(self):
        """验证默认字段值."""
        sr = SearchResult(event={"content": "hello"})
        assert sr.score == 0.0
        assert sr.source == "event"
        assert sr.interactions == []

    def test_to_public_excludes_internal(self):
        """验证 to_public 不含 score/source."""
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
        """验证 to_public 含 interactions."""
        sr = SearchResult(event={"content": "hello"}, interactions=[{"q": "x"}])
        pub = sr.to_public()
        assert pub["interactions"] == [{"q": "x"}]

    def test_to_public_no_interactions(self):
        """验证无 interactions 时 to_public 不含该字段."""
        sr = SearchResult(event={"content": "hello"})
        pub = sr.to_public()
        assert "interactions" not in pub


class TestFeedbackData:
    """FeedbackData 模型测试."""

    def test_extra_fields(self):
        """验证 modified_content 字段."""
        fb = FeedbackData(action="accept", modified_content="new")
        assert fb.modified_content == "new"

    def test_model_dump(self):
        """验证 model_dump 序列化输出."""
        fb = FeedbackData(event_id="x", action="accept")
        d = fb.model_dump()
        assert d["event_id"] == "x"


class TestInteractionRecord:
    """InteractionRecord 模型测试."""

    def test_default_fields(self):
        """验证默认字段值."""
        ir = InteractionRecord(id="x", query="q", response="r")
        assert ir.event_id == ""
        assert ir.memory_strength == 1
