"""app.memory.components 可组合组件测试."""

import math

import pytest

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    MemoryBankEngine,
    SimpleInteractionWriter,
    forgetting_curve,
)
from app.memory.schemas import FeedbackData, MemoryEvent


class TestForgettingCurve:
    """Tests for the forgetting_curve decay function."""

    def test_zero_days_returns_one(self):
        """Verify retention is 1.0 when no time has elapsed."""
        assert forgetting_curve(0, 1) == 1.0

    def test_negative_days_returns_one(self):
        """Verify retention is 1.0 for negative elapsed days."""
        assert forgetting_curve(-5, 3) == 1.0

    def test_zero_strength_returns_zero(self):
        """Verify retention is 0.0 when memory strength is zero."""
        assert forgetting_curve(10, 0) == 0.0

    def test_negative_strength_returns_zero(self):
        """Verify retention is 0.0 when memory strength is negative."""
        assert forgetting_curve(10, -1) == 0.0

    def test_positive_decay(self):
        """Verify positive decay produces a value between 0 and 1."""
        result = forgetting_curve(10, 2)
        assert 0.0 < result < 1.0
        assert math.isclose(result, math.exp(-10 / 10))

    def test_higher_strength_slower_decay(self):
        """Verify that higher strength results in slower decay."""
        weak = forgetting_curve(10, 1)
        strong = forgetting_curve(10, 5)
        assert strong > weak


class TestEventStorage:
    """Tests for the EventStorage component."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Provide an EventStorage backed by a temp directory."""
        return EventStorage(str(tmp_path))

    def test_generate_id_format(self, storage):
        """Verify generated IDs follow the expected timestamp_uuid format."""
        eid = storage.generate_id()
        assert "_" in eid
        parts = eid.split("_")
        assert len(parts[0]) == 14
        assert len(parts[1]) == 8

    def test_read_events_empty(self, storage):
        """Verify reading from empty storage returns an empty list."""
        assert storage.read_events() == []

    def test_append_event_assigns_id_and_created_at(self, storage):
        """Verify that append_event assigns an ID and created_at timestamp."""
        event = MemoryEvent(content="测试事件")
        eid = storage.append_event(event)
        events = storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == eid
        assert events[0]["created_at"] != ""

    def test_write_events_overwrites(self, storage):
        """Verify that write_events fully overwrites existing events."""
        storage.append_event(MemoryEvent(content="事件A"))
        storage.write_events([{"id": "x", "content": "覆盖"}])
        events = storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == "x"

    def test_multiple_appends(self, storage):
        """Verify that multiple appends accumulate correctly."""
        storage.append_event(MemoryEvent(content="A"))
        storage.append_event(MemoryEvent(content="B"))
        assert len(storage.read_events()) == 2


class TestKeywordSearch:
    """Tests for the KeywordSearch component."""

    @pytest.fixture
    def search(self):
        """Provide a KeywordSearch instance."""
        return KeywordSearch()

    @pytest.fixture
    def events(self):
        """Provide a list of sample event dicts."""
        return [
            {"content": "明天天气晴朗", "description": ""},
            {"content": "项目进度会议", "description": "讨论Q2计划"},
            {"content": "Hello World", "description": ""},
        ]

    def test_case_insensitive(self, search, events):
        """Verify keyword search is case-insensitive."""
        results = search.search("hello", events)
        assert len(results) == 1

    def test_matches_content(self, search, events):
        """Verify keyword search matches against event content."""
        results = search.search("天气", events)
        assert len(results) == 1
        assert "天气" in results[0].event["content"]

    def test_matches_description(self, search, events):
        """Verify keyword search matches against event description."""
        results = search.search("Q2", events)
        assert len(results) == 1

    def test_no_match(self, search, events):
        """Verify keyword search returns empty when nothing matches."""
        results = search.search("不存在", events)
        assert len(results) == 0

    def test_top_k_limits_results(self, search):
        """Verify that top_k parameter limits the number of results."""
        events = [{"content": f"天气事件{i}", "description": ""} for i in range(20)]
        results = search.search("天气", events, top_k=5)
        assert len(results) == 5

    def test_empty_events(self, search):
        """Verify keyword search handles empty event list."""
        results = search.search("天气", [])
        assert len(results) == 0


class TestFeedbackManager:
    """Tests for the FeedbackManager component."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Provide a FeedbackManager backed by a temp directory."""
        return FeedbackManager(str(tmp_path))

    def test_accept_increases_weight(self, manager, tmp_path):
        """Verify that accept feedback increases the strategy weight."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid1", FeedbackData(action="accept", type="meeting"))
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["meeting"] == pytest.approx(0.6)

    def test_ignore_decreases_weight(self, manager, tmp_path):
        """Verify that ignore feedback decreases the strategy weight."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid2", FeedbackData(action="ignore", type="general"))
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["general"] == pytest.approx(0.4)

    def test_accept_capped_at_one(self, manager, tmp_path):
        """Verify that accept weight is capped at 1.0."""
        from app.storage.json_store import JSONStore

        for _ in range(20):
            manager.update_feedback(
                "eid", FeedbackData(action="accept", type="meeting")
            )
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["meeting"] <= 1.0

    def test_ignore_floored_at_zero_point_one(self, manager, tmp_path):
        """Verify that ignore weight is floored at 0.1."""
        from app.storage.json_store import JSONStore

        for _ in range(20):
            manager.update_feedback(
                "eid", FeedbackData(action="ignore", type="general")
            )
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["general"] >= 0.1

    def test_feedback_appended_to_history(self, manager, tmp_path):
        """Verify that each feedback entry is appended to the history."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid1", FeedbackData(action="accept", type="meeting"))
        manager.update_feedback("eid2", FeedbackData(action="ignore", type="general"))
        feedback = JSONStore(str(tmp_path), "feedback.json", list).read()
        assert len(feedback) == 2


class TestSimpleInteractionWriter:
    """Tests for the SimpleInteractionWriter component."""

    @pytest.fixture
    def writer(self, tmp_path):
        """Provide a SimpleInteractionWriter backed by a temp EventStorage."""
        storage = EventStorage(str(tmp_path))
        return SimpleInteractionWriter(storage)

    def test_write_returns_id(self, writer):
        """Verify that write_interaction returns a non-empty ID."""
        iid = writer.write_interaction("查询", "响应")
        assert isinstance(iid, str)
        assert len(iid) > 0

    def test_write_stores_content_and_description(self, writer, tmp_path):
        """Verify that query and response are stored as content and description."""
        writer.write_interaction("查询内容", "响应内容")
        events = EventStorage(str(tmp_path)).read_events()
        assert len(events) == 1
        assert events[0]["content"] == "查询内容"
        assert events[0]["description"] == "响应内容"

    def test_write_custom_event_type(self, writer, tmp_path):
        """Verify that a custom event_type is stored correctly."""
        writer.write_interaction("查询", "响应", event_type="meeting")
        events = EventStorage(str(tmp_path)).read_events()
        assert events[0]["type"] == "meeting"


class TestMemoryBankEngineWrite:
    """Tests for MemoryBankEngine.write and search."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Provide an EventStorage backed by a temp directory."""
        return EventStorage(str(tmp_path))

    @pytest.fixture
    def engine(self, tmp_path, storage):
        """Provide a MemoryBankEngine without embedding or chat model."""
        return MemoryBankEngine(str(tmp_path), storage)

    def test_write_returns_id(self, engine):
        """Verify that write returns a non-empty event ID."""
        eid = engine.write(MemoryEvent(content="测试事件"))
        assert isinstance(eid, str)
        assert len(eid) > 0

    def test_write_sets_defaults(self, engine, storage):
        """Verify that write sets memory_strength, last_recall_date, and date_group."""
        engine.write(MemoryEvent(content="测试事件"))
        events = storage.read_events()
        assert events[0]["memory_strength"] == 1
        assert events[0]["last_recall_date"] != ""
        assert events[0]["date_group"] != ""

    def test_search_empty_returns_empty(self, engine):
        """Verify that searching with no events returns an empty list."""
        assert engine.search("测试") == []

    def test_search_blank_query_returns_empty(self, engine):
        """Verify that a blank query returns an empty list."""
        engine.write(MemoryEvent(content="测试"))
        assert engine.search("   ") == []

    def test_keyword_search_finds_match(self, engine):
        """Verify that keyword search finds a matching event."""
        engine.write(MemoryEvent(content="天气晴朗"))
        results = engine.search("天气")
        assert len(results) > 0
        assert "天气" in results[0].event["content"]

    def test_search_strengthens_matched_events(self, engine, storage):
        """Verify that searching strengthens the memory of matched events."""
        engine.write(MemoryEvent(content="重要会议"))
        engine.search("会议")
        events = storage.read_events()
        assert events[0]["memory_strength"] == 2


class TestMemoryBankEngineWriteInteraction:
    """Tests for MemoryBankEngine.write_interaction."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Provide an EventStorage backed by a temp directory."""
        return EventStorage(str(tmp_path))

    @pytest.fixture
    def engine(self, tmp_path, storage):
        """Provide a MemoryBankEngine without embedding or chat model."""
        return MemoryBankEngine(str(tmp_path), storage)

    def test_write_interaction_returns_id(self, engine):
        """Verify that write_interaction returns a non-empty interaction ID."""
        iid = engine.write_interaction("查询", "响应")
        assert isinstance(iid, str)
        assert len(iid) > 0

    def test_write_interaction_creates_event_and_interaction(self, engine, storage):
        """Verify that write_interaction creates both an event and interaction."""
        engine.write_interaction("提醒我开会", "好的")
        events = storage.read_events()
        interactions = engine._interactions_store.read()
        assert len(events) == 1
        assert len(interactions) == 1
        assert interactions[0]["event_id"] == events[0]["id"]

    def test_similar_interactions_aggregate_to_same_event(self, engine, storage):
        """Verify that similar interactions aggregate into the same event."""
        engine.write_interaction("明天上午开会", "好的")
        engine.write_interaction("明天上午开会讨论", "已更新")
        events = storage.read_events()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
