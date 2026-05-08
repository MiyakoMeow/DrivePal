"""app.memory.components 可组合组件测试."""

from pathlib import Path

import pytest

from app.memory.components import (
    ActionRequiredError,
    FeedbackManager,
)
from app.memory.schemas import FeedbackData
from app.storage.toml_store import TOMLStore

WEIGHT_MIN = 0.1
FEEDBACK_RECORD_COUNT_2 = 2


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
        strategies = await TOMLStore(
            tmp_path / "default", Path("strategies.toml"), dict
        ).read()
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
        strategies = await TOMLStore(
            tmp_path / "default", Path("strategies.toml"), dict
        ).read()
        assert strategies["reminder_weights"]["general"] == pytest.approx(0.4)

    async def test_action_none_raises_error(self, manager: FeedbackManager) -> None:
        """验证 action=None 时抛出 ActionRequiredError."""
        with pytest.raises(ActionRequiredError):
            await manager.update_feedback(
                "eid",
                FeedbackData(action=None, type="test"),
            )

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
        strategies = await TOMLStore(
            tmp_path / "default", Path("strategies.toml"), dict
        ).read()
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
        strategies = await TOMLStore(
            tmp_path / "default", Path("strategies.toml"), dict
        ).read()
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
        feedback = await TOMLStore(
            tmp_path / "default", Path("feedback.toml"), list
        ).read()
        assert len(feedback) == FEEDBACK_RECORD_COUNT_2
