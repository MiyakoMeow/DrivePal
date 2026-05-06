"""测试 BackgroundWorker。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.worker import BackgroundWorker


class TestBackgroundWorker:
    """给定 mock 依赖的 worker。"""

    @pytest.fixture
    def mock_index(self):
        """fixture: mock VectorIndex。"""
        idx = MagicMock()
        idx.save = AsyncMock()
        idx.add_vector = AsyncMock(return_value=42)
        return idx

    @pytest.fixture
    def mock_summarizer(self):
        """fixture: mock SummarizationService。"""
        s = MagicMock()
        s.get_daily_summary = AsyncMock(return_value="Daily text")
        s.get_overall_summary = AsyncMock(return_value="Overall")
        s.get_daily_personality = AsyncMock(return_value="Personality")
        s.get_overall_personality = AsyncMock(return_value="Overall P")
        return s

    @pytest.fixture
    def mock_encoder(self):
        """fixture: mock EmbeddingModel。"""
        e = MagicMock()
        e.encode = AsyncMock(return_value=[0.1, 0.2, 0.3])
        return e

    @pytest.fixture
    def worker(self, mock_index, mock_summarizer, mock_encoder):
        """fixture: 全依赖 worker。"""
        return BackgroundWorker(mock_index, mock_summarizer, mock_encoder)

    async def test_schedule_triggers_summary_pipeline(
        self,
        worker,
        mock_summarizer,
        mock_encoder,
        mock_index,
    ):
        """调度后完整摘要流水线被触发。"""
        worker.schedule_summarize("2026-05-06")
        await worker.drain()
        mock_summarizer.get_daily_summary.assert_awaited_once_with("2026-05-06")
        mock_encoder.encode.assert_awaited_once()
        mock_index.add_vector.assert_awaited_once()
        mock_summarizer.get_overall_summary.assert_awaited_once()
        mock_summarizer.get_daily_personality.assert_awaited_once_with("2026-05-06")
        mock_summarizer.get_overall_personality.assert_awaited_once()

    async def test_no_encoder_skips_encode(self, mock_index, mock_summarizer):
        """无 encoder 时不调用 add_vector。"""
        worker = BackgroundWorker(mock_index, mock_summarizer, encoder=None)
        worker.schedule_summarize("2026-05-06")
        await worker.drain()
        mock_index.add_vector.assert_not_awaited()

    async def test_no_summarizer_skips_all(self, mock_index, mock_encoder):
        """无 summarizer 时跳过所有操作。"""
        worker = BackgroundWorker(mock_index, summarizer=None, encoder=mock_encoder)
        worker.schedule_summarize("2026-05-06")
        await worker.drain()
        mock_index.add_vector.assert_not_awaited()
