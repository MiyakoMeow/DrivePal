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
    """遗忘曲线衰减函数测试."""

    def test_zero_days_returns_one(self) -> None:
        """验证无时间流逝时保留率为 1.0."""
        assert forgetting_curve(0, 1) == 1.0

    def test_negative_days_returns_one(self) -> None:
        """验证负数天数时保留率为 1.0."""
        assert forgetting_curve(-5, 3) == 1.0

    def test_zero_strength_returns_zero(self) -> None:
        """验证记忆强度为零时保留率为 0.0."""
        assert forgetting_curve(10, 0) == 0.0

    def test_negative_strength_returns_zero(self) -> None:
        """验证记忆强度为负时保留率为 0.0."""
        assert forgetting_curve(10, -1) == 0.0

    def test_positive_decay(self) -> None:
        """验证正衰减产生 0 到 1 之间的值."""
        result = forgetting_curve(10, 2)
        assert 0.0 < result < 1.0
        assert math.isclose(result, math.exp(-10 / 10))

    def test_higher_strength_slower_decay(self) -> None:
        """验证更高的强度导致更慢的衰减."""
        weak = forgetting_curve(10, 1)
        strong = forgetting_curve(10, 5)
        assert strong > weak


class TestEventStorage:
    """EventStorage 组件测试."""

    @pytest.fixture
    def storage(self, tmp_path: str) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(str(tmp_path))

    def test_generate_id_format(self, storage: EventStorage) -> None:
        """验证生成的 ID 遵循 timestamp_uuid 格式."""
        eid = storage.generate_id()
        assert "_" in eid
        parts = eid.split("_")
        assert len(parts[0]) == 14
        assert len(parts[1]) == 8

    def test_read_events_empty(self, storage: EventStorage) -> None:
        """验证从空存储读取返回空列表."""
        assert storage.read_events() == []

    def test_append_event_assigns_id_and_created_at(
        self, storage: EventStorage
    ) -> None:
        """验证 append_event 分配 ID 和 created_at 时间戳."""
        event = MemoryEvent(content="测试事件")
        eid = storage.append_event(event)
        events = storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == eid
        assert events[0]["created_at"] != ""

    def test_write_events_overwrites(self, storage: EventStorage) -> None:
        """验证 write_events 完全覆盖现有事件."""
        storage.append_event(MemoryEvent(content="事件A"))
        storage.write_events([{"id": "x", "content": "覆盖"}])
        events = storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == "x"

    def test_multiple_appends(self, storage: EventStorage) -> None:
        """验证多次追加能正确累积."""
        storage.append_event(MemoryEvent(content="A"))
        storage.append_event(MemoryEvent(content="B"))
        assert len(storage.read_events()) == 2


class TestKeywordSearch:
    """KeywordSearch 组件测试."""

    @pytest.fixture
    def search(self) -> KeywordSearch:
        """提供 KeywordSearch 实例."""
        return KeywordSearch()

    @pytest.fixture
    def events(self) -> list:
        """提供示例事件字典列表."""
        return [
            {"content": "明天天气晴朗", "description": ""},
            {"content": "项目进度会议", "description": "讨论Q2计划"},
            {"content": "Hello World", "description": ""},
        ]

    def test_case_insensitive(self, search: KeywordSearch, events: list) -> None:
        """验证关键词搜索不区分大小写."""
        results = search.search("hello", events)
        assert len(results) == 1

    def test_matches_content(self, search: KeywordSearch, events: list) -> None:
        """验证关键词搜索匹配事件内容."""
        results = search.search("天气", events)
        assert len(results) == 1
        assert "天气" in results[0].event["content"]

    def test_matches_description(self, search: KeywordSearch, events: list) -> None:
        """验证关键词搜索匹配事件描述."""
        results = search.search("Q2", events)
        assert len(results) == 1

    def test_no_match(self, search: KeywordSearch, events: list) -> None:
        """验证关键词搜索在不匹配时返回空."""
        results = search.search("不存在", events)
        assert len(results) == 0

    def test_top_k_limits_results(self, search: KeywordSearch) -> None:
        """验证 top_k 参数限制结果数量."""
        events = [{"content": f"天气事件{i}", "description": ""} for i in range(20)]
        results = search.search("天气", events, top_k=5)
        assert len(results) == 5

    def test_empty_events(self, search: KeywordSearch) -> None:
        """验证关键词搜索处理空事件列表."""
        results = search.search("天气", [])
        assert len(results) == 0


class TestFeedbackManager:
    """FeedbackManager 组件测试."""

    @pytest.fixture
    def manager(self, tmp_path: str) -> FeedbackManager:
        """提供由临时目录支持的 FeedbackManager."""
        return FeedbackManager(str(tmp_path))

    def test_accept_increases_weight(
        self, manager: FeedbackManager, tmp_path: str
    ) -> None:
        """验证接受反馈增加策略权重."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid1", FeedbackData(action="accept", type="meeting"))
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["meeting"] == pytest.approx(0.6)

    def test_ignore_decreases_weight(
        self, manager: FeedbackManager, tmp_path: str
    ) -> None:
        """验证忽略反馈降低策略权重."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid2", FeedbackData(action="ignore", type="general"))
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["general"] == pytest.approx(0.4)

    def test_accept_capped_at_one(
        self, manager: FeedbackManager, tmp_path: str
    ) -> None:
        """验证接受权重上限为 1.0."""
        from app.storage.json_store import JSONStore

        for _ in range(20):
            manager.update_feedback(
                "eid", FeedbackData(action="accept", type="meeting")
            )
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["meeting"] <= 1.0

    def test_ignore_floored_at_zero_point_one(
        self, manager: FeedbackManager, tmp_path: str
    ) -> None:
        """验证忽略权重下限为 0.1."""
        from app.storage.json_store import JSONStore

        for _ in range(20):
            manager.update_feedback(
                "eid", FeedbackData(action="ignore", type="general")
            )
        strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
        assert strategies["reminder_weights"]["general"] >= 0.1

    def test_feedback_appended_to_history(
        self, manager: FeedbackManager, tmp_path: str
    ) -> None:
        """验证每条反馈记录都追加到历史记录中."""
        from app.storage.json_store import JSONStore

        manager.update_feedback("eid1", FeedbackData(action="accept", type="meeting"))
        manager.update_feedback("eid2", FeedbackData(action="ignore", type="general"))
        feedback = JSONStore(str(tmp_path), "feedback.json", list).read()
        assert len(feedback) == 2


class TestSimpleInteractionWriter:
    """SimpleInteractionWriter 组件测试."""

    @pytest.fixture
    def writer(self, tmp_path: str) -> SimpleInteractionWriter:
        """提供由临时 EventStorage 支持的 SimpleInteractionWriter."""
        storage = EventStorage(str(tmp_path))
        return SimpleInteractionWriter(storage)

    def test_write_returns_id(self, writer: SimpleInteractionWriter) -> None:
        """验证 write_interaction 返回非空 ID."""
        iid = writer.write_interaction("查询", "响应")
        assert isinstance(iid, str)
        assert len(iid) > 0

    def test_write_stores_content_and_description(
        self, writer: SimpleInteractionWriter, tmp_path: str
    ) -> None:
        """验证查询和响应存储为 content 和 description."""
        writer.write_interaction("查询内容", "响应内容")
        events = EventStorage(str(tmp_path)).read_events()
        assert len(events) == 1
        assert events[0]["content"] == "查询内容"
        assert events[0]["description"] == "响应内容"

    def test_write_custom_event_type(
        self, writer: SimpleInteractionWriter, tmp_path: str
    ) -> None:
        """验证自定义 event_type 被正确存储."""
        writer.write_interaction("查询", "响应", event_type="meeting")
        events = EventStorage(str(tmp_path)).read_events()
        assert events[0]["type"] == "meeting"


class TestMemoryBankEngineWrite:
    """MemoryBankEngine.write 和 search 测试."""

    @pytest.fixture
    def storage(self, tmp_path: str) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(str(tmp_path))

    @pytest.fixture
    def engine(self, tmp_path: str, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(str(tmp_path), storage)

    def test_write_returns_id(self, engine: MemoryBankEngine) -> None:
        """验证 write 返回非空事件 ID."""
        eid = engine.write(MemoryEvent(content="测试事件"))
        assert isinstance(eid, str)
        assert len(eid) > 0

    def test_write_sets_defaults(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证 write 设置 memory_strength、last_recall_date 和 date_group."""
        engine.write(MemoryEvent(content="测试事件"))
        events = storage.read_events()
        assert events[0]["memory_strength"] == 1
        assert events[0]["last_recall_date"] != ""
        assert events[0]["date_group"] != ""

    def test_search_empty_returns_empty(self, engine: MemoryBankEngine) -> None:
        """验证无事件时搜索返回空列表."""
        assert engine.search("测试") == []

    def test_search_blank_query_returns_empty(self, engine: MemoryBankEngine) -> None:
        """验证空白查询返回空列表."""
        engine.write(MemoryEvent(content="测试"))
        assert engine.search("   ") == []

    def test_keyword_search_finds_match(self, engine: MemoryBankEngine) -> None:
        """验证关键词搜索能找到匹配的事件."""
        engine.write(MemoryEvent(content="天气晴朗"))
        results = engine.search("天气")
        assert len(results) > 0
        assert "天气" in results[0].event["content"]

    def test_search_strengthens_matched_events(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证搜索增强匹配事件的记忆."""
        engine.write(MemoryEvent(content="重要会议"))
        engine.search("会议")
        events = storage.read_events()
        assert events[0]["memory_strength"] == 2


class TestMemoryBankEngineWriteInteraction:
    """MemoryBankEngine.write_interaction 测试."""

    @pytest.fixture
    def storage(self, tmp_path: str) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(str(tmp_path))

    @pytest.fixture
    def engine(self, tmp_path: str, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(str(tmp_path), storage)

    def test_write_interaction_returns_id(self, engine: MemoryBankEngine) -> None:
        """验证 write_interaction 返回非空交互 ID."""
        iid = engine.write_interaction("查询", "响应")
        assert isinstance(iid, str)
        assert len(iid) > 0

    def test_write_interaction_creates_event_and_interaction(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证 write_interaction 同时创建事件和交互."""
        engine.write_interaction("提醒我开会", "好的")
        events = storage.read_events()
        interactions = engine._interactions_store.read()
        assert len(events) == 1
        assert len(interactions) == 1
        assert interactions[0]["event_id"] == events[0]["id"]

    def test_similar_interactions_aggregate_to_same_event(
        self, engine: MemoryBankEngine, storage: EventStorage
    ) -> None:
        """验证相似的交互聚合到同一事件."""
        engine.write_interaction("明天上午开会", "好的")
        engine.write_interaction("明天上午开会讨论", "已更新")
        events = storage.read_events()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
