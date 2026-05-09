"""测试 PendingReminderManager."""

import asyncio

import pytest

from app.agents.outputs import InterruptLevel, MultiFormatContent, OutputChannel
from app.agents.pending import PendingReminderManager


@pytest.fixture
def tmp_user_dir(tmp_path):
    d = tmp_path / "default"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sample_content():
    return MultiFormatContent(
        speakable_text="到家提醒",
        display_text="到家",
        detailed="到家提醒",
        channel=OutputChannel.AUDIO,
        interrupt_level=InterruptLevel.NORMAL,
    )


class TestPendingReminderCRUD:
    async def test_add_and_list(self, tmp_user_dir, sample_content):
        """Given 空 PendingReminderManager, When add 一条提醒, Then list 返回1条."""
        pm = PendingReminderManager(tmp_user_dir)
        pr = await pm.add(
            content=sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达目的地时",
        )
        assert pr.id.startswith("pr_")
        assert pr.status == "pending"

        all_reminders = await pm.list_pending()
        assert len(all_reminders) == 1

    async def test_cancel(self, tmp_user_dir, sample_content):
        """Given 一条 pending reminder, When cancel, Then status 变为 cancelled."""
        pm = PendingReminderManager(tmp_user_dir)
        pr = await pm.add(sample_content, "location", {}, "evt_001")
        await pm.cancel(pr.id)
        assert len(await pm.list_pending()) == 0

    async def test_cancel_last_no_pending(self, tmp_user_dir, sample_content):
        """Given 空队列, When cancel_last, Then 返回 False."""
        pm = PendingReminderManager(tmp_user_dir)
        cancelled = await pm.cancel_last()
        assert cancelled is False

    async def test_cancel_last_with_pending(self, tmp_user_dir, sample_content):
        """Given 有 pending, When cancel_last, Then 取消最近一条."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(sample_content, "location", {}, "evt_001")
        await pm.add(sample_content, "location", {}, "evt_002")
        cancelled = await pm.cancel_last()
        assert cancelled is True
        pending = await pm.list_pending()
        assert len(pending) == 1
        assert pending[0]["event_id"] == "evt_001"


class TestPollingTriggerLocation:
    async def test_location_trigger_within_range(self, tmp_user_dir, sample_content):
        """Given location trigger, When GPS 在目标附近, Then 触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
        )
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 31.23, "longitude": 121.47}}}
        )
        assert len(triggered) == 1

    async def test_location_too_far_not_triggered(self, tmp_user_dir, sample_content):
        """Given location trigger, When GPS 距离 > 500m, Then 不触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
        )
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 30.00, "longitude": 120.00}}}
        )
        assert len(triggered) == 0

    async def test_parked_within_range_triggers(self, tmp_user_dir, sample_content):
        """Given location trigger, When scenario=parked 且在放宽半径内, Then 触发（不等精确 500m）."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
        )
        # 约 0.01 度 ≈ 950m，在停车放宽半径 1000m 内
        triggered = await pm.poll(
            {
                "scenario": "parked",
                "spatial": {
                    "current_location": {"latitude": 31.23, "longitude": 121.48}
                },
            }
        )
        assert len(triggered) == 1

    async def test_parked_far_away_not_triggered(self, tmp_user_dir, sample_content):
        """Given location trigger, When scenario=parked 但远超放宽半径, Then 不触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
        )
        triggered = await pm.poll(
            {
                "scenario": "parked",
                "spatial": {
                    "current_location": {"latitude": 30.00, "longitude": 120.00}
                },
            }
        )
        assert len(triggered) == 0

    async def test_no_location_data_not_triggered(self, tmp_user_dir, sample_content):
        """Given 无 GPS 数据, When poll, Then 不触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
        )
        triggered = await pm.poll({"scenario": "city_driving"})
        assert len(triggered) == 0


class TestPollingTriggerTime:
    async def test_ttl_expiry(self, tmp_user_dir, sample_content):
        """Given TTL=1s, When 等待 1.5s 后 poll, Then 自动 cancel."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            trigger_text="到达",
            ttl_seconds=1,
        )
        await asyncio.sleep(1.5)
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 31.23, "longitude": 121.47}}}
        )
        assert len(triggered) == 0  # TTL 过期


class TestPollingTriggerContext:
    async def test_context_trigger_scenario_change(self, tmp_user_dir, sample_content):
        """Given context trigger, When scenario 切换, Then 触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="context",
            trigger_target={"previous_scenario": "highway"},
            event_id="evt_001",
            trigger_text="场景恢复时",
        )
        triggered = await pm.poll({"scenario": "parked"})
        assert len(triggered) == 1

    async def test_context_trigger_same_scenario_not_triggered(
        self, tmp_user_dir, sample_content
    ):
        """Given context trigger, When scenario 未变, Then 不触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="context",
            trigger_target={"previous_scenario": "highway"},
            event_id="evt_001",
            trigger_text="场景恢复时",
        )
        triggered = await pm.poll({"scenario": "highway"})
        assert len(triggered) == 0
