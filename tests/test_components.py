"""app.memory.components 可组合组件测试."""

import inspect
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    SimpleInteractionWriter,
    forgetting_curve,
)
from app.memory.schemas import FeedbackData, InteractionResult, MemoryEvent
from app.memory.stores.memory_bank.engine import (
    SOFT_FORGET_STRENGTH,
    MemoryBankEngine,
)
from app.memory.stores.memory_bank.personality import PersonalityManager
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

    async def test_write_preserves_existing_date_group(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 write 保留传入的 date_group."""
        await engine.write(MemoryEvent(content="历史事件", date_group="2025-03-10"))
        events = await storage.read_events()
        assert events[0]["date_group"] == "2025-03-10"

    async def test_write_preserves_existing_last_recall_date(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 write 保留传入的 last_recall_date."""
        await engine.write(
            MemoryEvent(content="历史事件", last_recall_date="2025-03-10"),
        )
        events = await storage.read_events()
        assert events[0]["last_recall_date"] == "2025-03-10"

    async def test_write_defaults_date_group_when_empty(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 date_group 为空时使用当天日期."""
        await engine.write(MemoryEvent(content="新事件"))
        events = await storage.read_events()
        assert events[0]["date_group"] != ""

    async def test_write_defaults_last_recall_date_to_date_group(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 last_recall_date 为空时使用 date_group."""
        await engine.write(MemoryEvent(content="新事件", date_group="2025-06-01"))
        events = await storage.read_events()
        assert events[0]["last_recall_date"] == "2025-06-01"

    async def test_write_batch_returns_ids(
        self,
        engine: MemoryBankEngine,
    ) -> None:
        """验证 write_batch 返回所有事件 ID."""
        events = [
            MemoryEvent(content="事件1"),
            MemoryEvent(content="事件2"),
        ]
        ids = await engine.write_batch(events)
        assert len(ids) == len(events)
        assert all(isinstance(i, str) and len(i) > 0 for i in ids)

    async def test_write_batch_preserves_date_groups(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 write_batch 保留不同的 date_group."""
        await engine.write_batch(
            [
                MemoryEvent(content="三月事件", date_group="2025-03-10"),
                MemoryEvent(content="四月事件", date_group="2025-04-15"),
            ]
        )
        events = await storage.read_events()
        dates = {e["date_group"] for e in events}
        assert "2025-03-10" in dates
        assert "2025-04-15" in dates


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

    async def test_personality_prompt_is_preference_profile(
        self,
        engine: MemoryBankEngine,  # noqa: ARG002
    ) -> None:
        """验证人格分析 prompt 使用偏好画像模板."""
        source = inspect.getsource(PersonalityManager.maybe_summarize)
        assert "vehicle preference profile" in source

    async def test_overall_personality_prompt_is_preference_summary(
        self,
        engine: MemoryBankEngine,  # noqa: ARG002
    ) -> None:
        """验证总体人格 prompt 使用偏好汇总模板."""
        source = inspect.getsource(PersonalityManager.generate_overall_text)
        assert "preference summary" in source


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

    async def test_search_does_not_forget_unmatched(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证搜索时遗忘过期事件（forget_expired 在搜索末尾自动调用）."""
        await engine.write(MemoryEvent(content="旧事件"))
        await engine.write(MemoryEvent(content="新事件"))
        events = await storage.read_events()
        old_event = next(e for e in events if e["content"] == "旧事件")
        old_event["last_recall_date"] = "2020-01-01"
        old_event["memory_strength"] = 1
        await storage.write_events(events)
        results = await engine.search("新事件")
        assert len(results) >= 1
        assert "新事件" in results[0].event.get("content", "")
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

    async def test_forget_expired_marks_old_events(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 forget_expired 正确遗忘过期事件."""
        await engine.write(MemoryEvent(content="旧事件"))
        await engine.write(MemoryEvent(content="新事件"))
        events = await storage.read_events()
        old_event = next(e for e in events if e["content"] == "旧事件")
        old_event["last_recall_date"] = "2020-01-01"
        old_event["memory_strength"] = 1
        await storage.write_events(events)
        await engine.forget_expired()
        updated_events = await storage.read_events()
        forgotten = next((e for e in updated_events if e["content"] == "旧事件"), None)
        assert forgotten is not None
        assert forgotten["forgotten"] is True
        assert forgotten["memory_strength"] == SOFT_FORGET_STRENGTH
        fresh = next(e for e in updated_events if e["content"] == "新事件")
        assert fresh.get("forgotten") is not True

    async def test_forget_expired_preserves_fresh_events(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 forget_expired 保留新近事件."""
        await engine.write(MemoryEvent(content="匹配事件"))
        await engine.write(MemoryEvent(content="完全不相关事件"))
        events = await storage.read_events()
        unmatched = next(e for e in events if e["content"] == "完全不相关事件")
        unmatched["last_recall_date"] = "2020-01-01"
        unmatched["memory_strength"] = 1
        await storage.write_events(events)
        await engine.forget_expired()
        events = await storage.read_events()
        matched = next(e for e in events if e["content"] == "匹配事件")
        unmatched = next(e for e in events if e["content"] == "完全不相关事件")
        assert matched.get("forgotten") is not True
        assert unmatched.get("forgotten") is True
        assert matched["memory_strength"] > unmatched["memory_strength"]


class TestForgettingCurve:
    """遗忘曲线函数测试."""

    def test_default_decay_base(self) -> None:
        """验证默认衰减基数为 5."""
        result = forgetting_curve(5, 1)
        assert result == pytest.approx(math.exp(-1.0))

    def test_custom_decay_base(self) -> None:
        """验证自定义衰减基数."""
        result = forgetting_curve(10, 1, decay_base=10)
        assert result == pytest.approx(math.exp(-1.0))

    def test_zero_days_returns_one(self) -> None:
        """验证 0 天经过返回 1.0."""
        assert forgetting_curve(0, 1) == 1.0

    def test_zero_strength_returns_zero(self) -> None:
        """验证 0 强度返回 0.0."""
        assert forgetting_curve(10, 0) == 0.0

    def test_larger_decay_base_slower_decay(self) -> None:
        """验证更大的衰减基数衰减更慢."""
        fast = forgetting_curve(10, 1, decay_base=5)
        slow = forgetting_curve(10, 1, decay_base=20)
        assert slow > fast


class TestSummaryPersonalityEmbeddingSearch:
    """Summary/Personality embedding 搜索测试."""

    @pytest.fixture
    def engine_with_mock_embedding(
        self,
        tmp_path: Path,
    ) -> tuple[MemoryBankEngine, MagicMock]:
        """提供带 mock embedding 模型的引擎."""
        storage = EventStorage(tmp_path)
        embedding = MagicMock()
        engine = MemoryBankEngine(tmp_path, storage, embedding_model=embedding)
        return engine, embedding

    async def test_summary_uses_embedding_search(
        self,
        engine_with_mock_embedding: tuple[MemoryBankEngine, MagicMock],
    ) -> None:
        """验证 summary 搜索使用 embedding 模型."""
        engine, embedding = engine_with_mock_embedding
        await engine.summaries_store.write(
            {
                "daily_summaries": {
                    "2025-03-10": {
                        "content": "Gary prefers green instrument panel",
                        "memory_strength": 1,
                        "last_recall_date": "2025-03-10",
                    },
                },
                "overall_summary": "",
            }
        )
        embedding.encode = AsyncMock(return_value=[0.1] * 10)
        embedding.batch_encode = AsyncMock(return_value=[[0.1] * 10])
        await engine._search_summaries_by_embedding(
            "instrument panel color",
            {
                "2025-03-10": {
                    "content": "Gary prefers green instrument panel",
                    "memory_strength": 1,
                    "last_recall_date": "2025-03-10",
                }
            },
            top_k=3,
        )
        embedding.batch_encode.assert_called_once()

    async def test_personality_uses_embedding_search(
        self,
        engine_with_mock_embedding: tuple[MemoryBankEngine, MagicMock],
    ) -> None:
        """验证 personality 搜索使用 embedding 模型."""
        engine, embedding = engine_with_mock_embedding
        await engine.personality_store.write(
            {
                "daily_personality": {
                    "2025-03-10": {
                        "content": "Gary likes green settings",
                        "memory_strength": 1,
                        "last_recall_date": "2025-03-10",
                    },
                },
                "overall_personality": "",
            }
        )
        embedding.encode = AsyncMock(return_value=[0.1] * 10)
        embedding.batch_encode = AsyncMock(return_value=[[0.1] * 10])
        await engine._search_personality_by_embedding(
            "color preference",
            {
                "daily_personality": {
                    "2025-03-10": {
                        "content": "Gary likes green settings",
                        "memory_strength": 1,
                        "last_recall_date": "2025-03-10",
                    },
                },
                "overall_personality": "",
            },
            top_k=3,
        )
        embedding.batch_encode.assert_called_once()

    async def test_summary_fallback_to_keyword_without_embedding(
        self,
        tmp_path: Path,
    ) -> None:
        """验证无 embedding 时 summary 回退到关键词搜索."""
        storage = EventStorage(tmp_path)
        engine = MemoryBankEngine(tmp_path, storage)
        daily_summaries = {
            "2025-03-10": {
                "content": "Gary prefers green instrument panel",
                "memory_strength": 1,
                "last_recall_date": "2025-03-10",
            },
        }
        results = await engine._search_summaries_by_embedding(
            "instrument panel",
            daily_summaries,
            top_k=3,
        )
        assert len(results) >= 1


class TestEventSummaryPrompt:
    """Event summary prompt 测试."""

    async def test_event_summary_prompt_is_english(self) -> None:
        """验证 event summary prompt 使用英文偏好保留模板."""
        source = inspect.getsource(MemoryBankEngine._update_event_summary)
        assert "vehicle-related preferences" in source


class TestForgetThrottle:
    """遗忘节流测试."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> EventStorage:
        """提供存储."""
        return EventStorage(tmp_path)

    @pytest.fixture
    def engine(self, tmp_path: Path, storage: EventStorage) -> MemoryBankEngine:
        """提供引擎."""
        return MemoryBankEngine(tmp_path, storage)

    async def test_forget_throttle_skips_recent_call(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证节流机制跳过短时间内重复遗忘."""
        await engine.write(MemoryEvent(content="事件"))
        engine._last_forget_time = time.monotonic()
        await engine.forget_expired()
        events = await storage.read_events()
        assert events[0].get("forgotten") is not True

    async def test_forget_force_bypasses_throttle(
        self,
        engine: MemoryBankEngine,
        storage: EventStorage,
    ) -> None:
        """验证 force=True 绕过节流."""
        await engine.write(MemoryEvent(content="旧事件"))
        events = await storage.read_events()
        events[0]["last_recall_date"] = "2020-01-01"
        await storage.write_events(events)
        engine._last_forget_time = time.monotonic()
        await engine.forget_expired(force=True)
        events = await storage.read_events()
        assert events[0]["forgotten"] is True
