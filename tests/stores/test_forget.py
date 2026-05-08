"""遗忘曲线单元测试（纯函数版）。"""

import random
from datetime import UTC, datetime

import pytest

from app.memory.memory_bank.forget import (
    ForgetMode,
    compute_ingestion_forget_ids,
    forgetting_retention,
)


class TestForgettingRetention:
    """遗忘留存率函数测试。"""

    def test_zero_days_full_retention(self):
        """验证 0 天经过留存率为 1.0。"""
        assert forgetting_retention(0, 1) == pytest.approx(1.0)

    def test_higher_strength_slows_forgetting(self):
        """验证更高强度减缓遗忘。"""
        assert forgetting_retention(5, 5) > forgetting_retention(5, 1)

    def test_longer_time_lower_retention(self):
        """验证更长时间降低留存率。"""
        assert forgetting_retention(1, 1) > forgetting_retention(10, 1)

    def test_negative_days_returns_one(self):
        """验证负数天数返回 1.0。"""
        assert forgetting_retention(-1, 1) == pytest.approx(1.0)

    def test_zero_strength_returns_zero(self):
        """验证零强度返回 0.0。"""
        assert forgetting_retention(1, 0) == pytest.approx(0.0)


class TestIngestionForget:
    """摄入时遗忘测试。"""

    def test_skip_daily_summary(self):
        """daily_summary 类型条目不受遗忘影响。"""
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            },
            {
                "faiss_id": 1,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
                "type": "daily_summary",
            },
            {
                "faiss_id": 2,
                "last_recall_date": "2024-06-10",
                "timestamp": "2024-06-10T00:00:00",
                "memory_strength": 5,
            },
        ]
        ids = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            mode=ForgetMode.DETERMINISTIC,
        )
        assert 1 not in ids

    def test_recent_entry_retained(self):
        """近期条目不应被遗忘。"""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": today,
                "timestamp": f"{today}T00:00:00",
                "memory_strength": 1,
            },
        ]
        ids = compute_ingestion_forget_ids(
            list(metadata),
            today,
            mode=ForgetMode.DETERMINISTIC,
        )
        assert 0 not in ids

    def test_seeded_reproducible(self):
        """相同 seed/RNG 产生相同结果。"""
        metadata = [
            {
                "faiss_id": i,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            }
            for i in range(50)
        ]
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        ids_a = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            rng=rng_a,
            mode=ForgetMode.PROBABILISTIC,
        )
        ids_b = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            rng=rng_b,
            mode=ForgetMode.PROBABILISTIC,
        )
        assert ids_a == ids_b

    def test_deterministic_old_entry_forgotten(self):
        """确定性模式下旧条目（retention < threshold）应被遗忘。"""
        metadata = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "last_recall_date": "2026-01-01",
            }
        ]
        ids = compute_ingestion_forget_ids(
            metadata,
            "2026-05-05",
            mode=ForgetMode.DETERMINISTIC,
        )
        assert 0 in ids

    def test_probabilistic_returns_ids_with_seed(self):
        """概率模式下返回被遗忘条目的 FAISS ID。"""
        metadata = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "last_recall_date": "2026-01-01",
            },
            {
                "faiss_id": 1,
                "memory_strength": 5,
                "timestamp": "2026-05-05T00:00:00",
                "last_recall_date": "2026-05-05",
            },
        ]
        ids = compute_ingestion_forget_ids(
            metadata,
            "2026-05-05",
            rng=random.Random(42),
            mode=ForgetMode.PROBABILISTIC,
        )
        assert 0 in ids  # strength=1, 125天 → 必遗忘
        assert 1 not in ids  # strength=5, 当天 → 保留
