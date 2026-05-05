"""app.memory.components 可组合组件测试."""

from pathlib import Path

import pytest

from app.memory.components import FeedbackManager, KeywordSearch
from app.memory.schemas import FeedbackData
from app.storage.toml_store import TOMLStore

DEFAULT_TOP_K = 5
WEIGHT_MIN = 0.1
FEEDBACK_RECORD_COUNT_2 = 2


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
