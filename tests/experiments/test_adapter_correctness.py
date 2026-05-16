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

    def test_en_turn_on_detected(self):
        content = "Turn on the air conditioner"
        assert _resolve_strength(content) == 5

    def test_en_substring_no_false_positive(self):
        """英文词边界阻止子串误匹配。"""
        assert _resolve_strength("The sunset is beautiful") == 3
        assert _resolve_strength("Exchange the gift") == 3
        assert _resolve_strength("Unlikely to happen") == 3


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

        def capturing_add(self, content, strength=3, *, created_at=None, **kwargs):
            captured_created_at.append(created_at)
            if self._store is None:
                self._store = MagicMock()
                self._store.write = AsyncMock(return_value="evt_x")
            return original_add(
                self, content, strength=strength, created_at=created_at, **kwargs
            )

        with patch.object(DrivePalMemClient, "add", capturing_add):
            # 向上遍历父目录查找 VehicleMemBench，避免 parents[N] 硬编码层级
            vmb_root: pathlib.Path | None = None
            for parent in pathlib.Path(__file__).resolve().parents:
                candidate = parent / "VehicleMemBench"
                if candidate.is_dir():
                    vmb_root = candidate
                    break
            if vmb_root is None:
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

            try:
                with patch(
                    "experiments.vehicle_mem_bench.adapter._DEFAULT_DATA_DIR",
                    tmp_path / "output",
                ):
                    run_add(args)
            finally:
                if str(vmb_root) in sys.path:
                    sys.path.remove(str(vmb_root))

        assert len(captured_created_at) == 1
        assert captured_created_at[0] is not None
        assert "2025-03-10" in captured_created_at[0]
