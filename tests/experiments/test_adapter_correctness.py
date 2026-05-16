"""VehicleMemBench 适配器正确性测试."""

import pathlib
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from experiments.vehicle_mem_bench.adapter import _resolve_strength


class TestPreferenceKeywords:
    """偏好关键词中英文匹配."""

    def test_cn_keywords_detect_chinese_preference(self):
        content = "用户设置空调温度为24度"
        assert _resolve_strength(content) == 5

    def test_cn_keywords_non_preference_returns_default(self):
        content = "今天天气不错"
        assert _resolve_strength(content) == 3

    def test_en_keywords_detect_english_preference(self):
        content = "Gary prefers green for the instrument panel"
        assert _resolve_strength(content) == 5

    def test_en_keywords_change_detected(self):
        content = "Can you change the seat position?"
        assert _resolve_strength(content) == 5

    def test_en_keywords_set_detected(self):
        content = "Set the volume to 30"
        assert _resolve_strength(content) == 5

    def test_en_keywords_switch_detected(self):
        content = "Switch to FM radio"
        assert _resolve_strength(content) == 5

    def test_en_non_preference_returns_default(self):
        content = "The weather is nice today"
        assert _resolve_strength(content) == 3

    def test_en_case_insensitive(self):
        content = "I PREFER the dark mode"
        assert _resolve_strength(content) == 5

    def test_en_adjust_detected(self):
        content = "Adjust the brightness please"
        assert _resolve_strength(content) == 5

    def test_en_want_detected(self):
        content = "I want cooler temperature"
        assert _resolve_strength(content) == 5


class TestMemoryCreatedAt:
    """记忆创建时间从 bucket.dt 注入."""

    def test_add_with_created_at_forwards_to_memory_event(self, tmp_path):
        """给定 created_at 参数，当 add 调用，则 MemoryEvent.created_at 使用给定值。"""
        from experiments.vehicle_mem_bench.adapter import DrivePalMemClient

        client = DrivePalMemClient(data_dir=tmp_path, user_id="test-ts")

        mock_store = MagicMock()
        mock_store.write = AsyncMock(return_value="evt_1")
        client._store = mock_store

        ts = "2025-06-15T14:00:00+00:00"
        client.add(content="test content", created_at=ts)

        call_args = mock_store.write.call_args
        event = call_args[0][0]
        assert event.created_at == ts

        client.close()

    def test_add_without_created_at_uses_now(self, tmp_path):
        """给定 created_at=None，当 add 调用，则使用 datetime.now()。"""
        from experiments.vehicle_mem_bench.adapter import DrivePalMemClient

        client = DrivePalMemClient(data_dir=tmp_path, user_id="test-ts2")

        mock_store = MagicMock()
        mock_store.write = AsyncMock(return_value="evt_2")
        client._store = mock_store

        before = datetime.now(UTC)
        client.add(content="test content", created_at=None)
        after = datetime.now(UTC)

        call_args = mock_store.write.call_args
        event = call_args[0][0]
        parsed = datetime.fromisoformat(event.created_at)
        assert before <= parsed <= after

        client.close()

    def test_run_add_passes_bucket_datetime(self, tmp_path):
        """给定 bucket.dt 有值，当 run_add processor 处理，则传给 client.add 的是 bucket 的 ISO 时间。"""
        from experiments.vehicle_mem_bench.adapter import DrivePalMemClient

        captured_created_at: list[str | None] = []

        original_add = DrivePalMemClient.add

        def capturing_add(self, content, strength=3, **kwargs):
            captured_created_at.append(kwargs.get("created_at"))
            if self._store is None:
                self._store = MagicMock()
                self._store.write = AsyncMock(return_value="evt_x")
            return original_add(self, content, strength=strength, **kwargs)

        with patch.object(DrivePalMemClient, "add", capturing_add):
            vmb_root = pathlib.Path(__file__).resolve().parents[5] / "VehicleMemBench"
            if not vmb_root.is_dir():
                pytest.skip("VehicleMemBench not found")
            if str(vmb_root) not in sys.path:
                sys.path.insert(0, str(vmb_root))

            from evaluation.memorysystems.common import HistoryBucket

            from experiments.vehicle_mem_bench.adapter import run_add

            history_dir = tmp_path / "history"
            history_dir.mkdir()
            history_file = history_dir / "history_1.txt"
            history_file.write_text("[2025-03-10 09:00] Gary prefers green dashboard\n")

            args = MagicMock()
            args.history_dir = str(history_dir)
            args.file_range = None
            args.max_workers = 1
            args.memory_url = None

            with patch(
                "experiments.vehicle_mem_bench.adapter._DEFAULT_DATA_DIR",
                tmp_path / "output",
            ):
                run_add(args)

            if str(vmb_root) in sys.path:
                sys.path.remove(str(vmb_root))

        assert len(captured_created_at) == 1
        assert captured_created_at[0] is not None
        assert "2025-03-10" in captured_created_at[0]
