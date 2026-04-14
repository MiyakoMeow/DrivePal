"""app.memory.components 可组合组件测试."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, InteractionResult, MemoryEvent
from app.memory.stores.memory_bank.engine import (
    SOFT_FORGET_STRENGTH,
    MemoryBankEngine,
)
from app.storage.toml_store import TOMLStore

# 测试常量定义
EXPECTED_EVENT_COUNT_2 = 2  # 预期事件数量
DEFAULT_TOP_K = 5  # 搜索默认返回数量
WEIGHT_MIN = 0.1  # 策略权重下限
FEEDBACK_RECORD_COUNT_2 = 2  # 反馈记录数量
SEARCH_BOOST_STRENGTH = 2  # 搜索增强后记忆强度


class TestEventStorage:
    """EventStorage 组件测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(tmp_path)

    async def test_read_events_empty(self, storage: EventStorage) -> None:
        """验证从空存储读取返回空列表."""
        assert await storage.read_events() == []

    async def test_append_event_assigns_id_and_created_at(
        self,
        storage: EventStorage,
    ) -> None:
        """验证 append_event 分配 ID 和 created_at 时间戳."""
        event = MemoryEvent(content="测试事件")
        eid = await storage.append_event(event)
        events = await storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == eid
        assert events[0]["created_at"] != ""

    async def test_write_events_overwrites(self, storage: EventStorage) -> None:
        """验证 write_events 完全覆盖现有事件."""
        await storage.append_event(MemoryEvent(content="事件A"))
        await storage.write_events([{"id": "x", "content": "覆盖"}])
        events = await storage.read_events()
        assert len(events) == 1
        assert events[0]["id"] == "x"

    async def test_multiple_appends(self, storage: EventStorage) -> None:
        """验证多次追加能正确累积."""
        await storage.append_event(MemoryEvent(content="A"))
        await storage.append_event(MemoryEvent(content="B"))
        assert len(await storage.read_events()) == EXPECTED_EVENT_COUNT_2


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
        assert len(results) == DEFAULT_TOP_K

    def test_empty_events(self, search: KeywordSearch) -> None:
        """验证关键词搜索处理空事件列表."""
        results = search.search("天气", [])
        assert len(results) == 0


class TestFeedbackManager:
    """FeedbackManager 组件测试."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> FeedbackManager:
        """提供由临时目录支持的 FeedbackManager."""
        return FeedbackManager(tmp_path)

    async def test_accept_increases_weight(
        self,
        manager: FeedbackManager,
        tmp_path: Path,
    ) -> None:
        """验证接受反馈增加策略权重."""
        await manager.update_feedback(
            "eid1",
            FeedbackData(action="accept", type="meeting"),
        )
        strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
        assert strategies["reminder_weights"]["meeting"] == pytest.approx(0.6)

    async def test_ignore_decreases_weight(
        self,
        manager: FeedbackManager,
        tmp_path: Path,
    ) -> None:
        """验证忽略反馈降低策略权重."""
        await manager.update_feedback(
            "eid2",
            FeedbackData(action="ignore", type="general"),
        )
        strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
        assert strategies["reminder_weights"]["general"] == pytest.approx(0.4)

    async def test_accept_capped_at_one(
        self,
        manager: FeedbackManager,
        tmp_path: Path,
    ) -> None:
        """验证接受权重上限为 1.0."""
        for _ in range(20):
            await manager.update_feedback(
                "eid",
                FeedbackData(action="accept", type="meeting"),
            )
        strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
        assert strategies["reminder_weights"]["meeting"] <= 1.0

    async def test_ignore_floored_at_zero_point_one(
        self,
        manager: FeedbackManager,
        tmp_path: Path,
    ) -> None:
        """验证忽略权重下限为 0.1."""
        for _ in range(20):
            await manager.update_feedback(
                "eid",
                FeedbackData(action="ignore", type="general"),
            )
        strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
        assert strategies["reminder_weights"]["general"] >= WEIGHT_MIN

    async def test_feedback_appended_to_history(
        self,
        manager: FeedbackManager,
        tmp_path: Path,
    ) -> None:
        """验证每条反馈记录都追加到历史记录中."""
        await manager.update_feedback(
            "eid1",
            FeedbackData(action="accept", type="meeting"),
        )
        await manager.update_feedback(
            "eid2",
            FeedbackData(action="ignore", type="general"),
        )
        feedback = await TOMLStore(tmp_path, Path("feedback.toml"), list).read()
        assert len(feedback) == FEEDBACK_RECORD_COUNT_2


class TestSimpleInteractionWriter:
    """SimpleInteractionWriter 组件测试."""

    @pytest.fixture
    def writer(self, tmp_path: Path) -> SimpleInteractionWriter:
        """提供由临时 EventStorage 支持的 SimpleInteractionWriter."""
        storage = EventStorage(tmp_path)
        return SimpleInteractionWriter(storage)

    async def test_write_returns_id(self, writer: SimpleInteractionWriter) -> None:
        """验证 write_interaction 返回 InteractionResult."""
        result = await writer.write_interaction("查询", "响应")
        assert isinstance(result, InteractionResult)
        assert len(result.event_id) > 0
        assert result.interaction_id == ""

    async def test_write_stores_content_and_description(
        self,
        writer: SimpleInteractionWriter,
        tmp_path: Path,
    ) -> None:
        """验证查询和响应存储为 content 和 description."""
        await writer.write_interaction("查询内容", "响应内容")
        events = await EventStorage(tmp_path).read_events()
        assert len(events) == 1
        assert events[0]["content"] == "查询内容"
        assert events[0]["description"] == "响应内容"

    async def test_write_custom_event_type(
        self,
        writer: SimpleInteractionWriter,
        tmp_path: Path,
    ) -> None:
        """验证自定义 event_type 被正确存储."""
        await writer.write_interaction("查询", "响应", event_type="meeting")
        events = await EventStorage(tmp_path).read_events()
        assert events[0]["type"] == "meeting"


class TestMemoryBankEngineWrite:
    """MemoryBankEngine.write 和 search 测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(tmp_path, storage)

    async def test_write_returns_id(self, engine: MemoryBankEngine) -> None:
        """验证 write 返回非空事件 ID."""
        eid = await engine.write(MemoryEvent(content="测试事件"))
        assert isinstance(eid, str)
        assert len(eid) > 0

    async def test_write_sets_defaults(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 write 设置 memory_strength、last_recall_date 和 date_group."""
        await engine.write(MemoryEvent(content="测试事件"))
        events = await storage.read_events()
        assert events[0]["memory_strength"] == 1
        assert events[0]["last_recall_date"] != ""
        assert events[0]["date_group"] != ""

    async def test_search_empty_returns_empty(self, engine: MemoryBankEngine) -> None:
        """验证无事件时搜索返回空列表."""
        assert await engine.search("测试") == []

    async def test_search_blank_query_returns_empty(
        self,
        engine: MemoryBankEngine,
    ) -> None:
        """验证空白查询返回空列表."""
        await engine.write(MemoryEvent(content="测试"))
        assert await engine.search("   ") == []


class TestMemoryBankEngineWriteInteraction:
    """MemoryBankEngine.write_interaction 测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(tmp_path, storage)

    async def test_write_interaction_creates_event_and_interaction(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 write_interaction 同时创建事件和交互."""
        await engine.write_interaction("提醒我开会", "好的")
        events = await storage.read_events()
        interactions = await engine._interactions_store.read()
        assert len(events) == 1
        assert len(interactions) == 1
        assert interactions[0]["event_id"] == events[0]["id"]


class TestPersonalitySummary:
    """人格摘要测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(tmp_path, storage)

    async def test_maybe_summarize_personality_skips_without_chat_model(
        self,
        engine: MemoryBankEngine,
    ) -> None:
        """验证无 chat_model 时跳过人格摘要."""
        today = datetime.now(UTC).date().isoformat()
        await engine._personality_mgr.maybe_summarize(today, [], [], None)
        personality_data = await engine.personality_store.read()
        assert personality_data["daily_personality"] == {}

    async def test_search_personality_returns_matching_summaries(
        self,
        engine: MemoryBankEngine,
    ) -> None:
        """验证人格摘要搜索返回匹配结果."""
        personality_data = {
            "daily_personality": {
                "2026-04-01": {
                    "content": "用户喜欢讨论天气",
                    "memory_strength": 1,
                    "last_recall_date": "2026-04-01",
                },
            },
            "overall_personality": "",
        }
        await engine.personality_store.write(personality_data)
        results = await engine._personality_mgr.search("天气", top_k=1)
        assert len(results) == 1
        assert results[0].source == "personality"
        assert "天气" in results[0].event["content"]

    async def test_search_personality_returns_empty_when_no_match(
        self,
        engine: MemoryBankEngine,
    ) -> None:
        """验证无匹配时返回空结果."""
        personality_data = {
            "daily_personality": {
                "2026-04-01": {
                    "content": "用户喜欢讨论天气",
                    "memory_strength": 1,
                    "last_recall_date": "2026-04-01",
                },
            },
            "overall_personality": "",
        }
        await engine.personality_store.write(personality_data)
        results = await engine._personality_mgr.search("音乐", top_k=1)
        assert len(results) == 0


class TestSoftForgetMechanism:
    """软遗忘机制测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供由临时目录支持的 EventStorage."""
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        """提供不带嵌入或聊天模型的 MemoryBankEngine."""
        return MemoryBankEngine(tmp_path, storage)

    async def test_soft_forget_reduces_low_retention_events(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 retention 过低的事件被软遗忘."""
        await engine.write(MemoryEvent(content="旧事件"))
        await engine.write(MemoryEvent(content="新事件"))
        events = await storage.read_events()
        old_event = next(e for e in events if e["content"] == "旧事件")
        old_event["last_recall_date"] = "2020-01-01"
        old_event["memory_strength"] = 1
        await storage.write_events(events)
        await engine.search("新事件")
        updated_events = await storage.read_events()
        forgotten = next((e for e in updated_events if e["content"] == "旧事件"), None)
        assert forgotten is not None
        assert forgotten["forgotten"] is True
        assert forgotten["memory_strength"] == SOFT_FORGET_STRENGTH

    async def test_soft_forget_preserves_matched_events(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证匹配的事件不被软遗忘."""
        await engine.write(MemoryEvent(content="重要事件"))
        await engine.search("重要事件")
        events = await storage.read_events()
        event = events[0]
        assert event.get("forgotten") is not True

    async def test_soft_forget_only_applies_to_unmatched(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证软遗忘只应用于未匹配的记忆."""
        await engine.write(MemoryEvent(content="匹配事件"))
        await engine.write(MemoryEvent(content="完全不相关事件"))
        events = await storage.read_events()
        unmatched = next(e for e in events if e["content"] == "完全不相关事件")
        unmatched["last_recall_date"] = "2020-01-01"
        unmatched["memory_strength"] = 1
        await storage.write_events(events)
        await engine.search("匹配事件")
        events = await storage.read_events()
        matched = next(e for e in events if e["content"] == "匹配事件")
        unmatched = next(e for e in events if e["content"] == "完全不相关事件")
        assert matched.get("forgotten") is not True
        assert unmatched.get("forgotten") is True
        assert matched["memory_strength"] > unmatched["memory_strength"]
