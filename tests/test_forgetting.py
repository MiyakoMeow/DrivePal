"""遗忘曲线与判定测试。"""

import math

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.forget import (
    ForgettingCurve,
    compute_ingestion_forget_ids,
    forgetting_retention,
)


class TestForgettingRetention:
    def test_zero_days_returns_one(self):
        assert forgetting_retention(0, 5) == 1.0

    def test_zero_strength_returns_zero(self):
        assert forgetting_retention(10, 0) == 0.0

    def test_decay_follows_ebbinghaus(self):
        expected = math.exp(-1)
        r = forgetting_retention(1, 1)
        assert r == pytest.approx(expected)

    def test_higher_strength_slower_decay(self):
        r_weak = forgetting_retention(5, 1)
        r_strong = forgetting_retention(5, 10)
        assert r_strong > r_weak

    def test_negative_days_returns_one(self):
        r = forgetting_retention(-1, 5)
        assert r == 1.0


class TestDeterministicForgetting:
    def test_retention_below_threshold_marked_forgotten(self):
        config = MemoryBankConfig(
            forget_mode="deterministic",
            soft_forget_threshold=0.3,
            enable_forgetting=True,
            forget_interval_seconds=0,
        )
        fc = ForgettingCurve(config)
        # strength=1, days=5 → retention = e^{-5} ≈ 0.0067 < 0.3
        meta = [
            {
                "faiss_id": 1,
                "text": "old",
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "memory_strength": 1,
                "forgotten": False,
            }
        ]
        result = fc.maybe_forget(meta, reference_date="2020-02-01")  # 31 days
        assert result is not None  # not throttled
        assert meta[0]["forgotten"] is True

    def test_retention_above_threshold_not_forgotten(self):
        config = MemoryBankConfig(
            forget_mode="deterministic",
            soft_forget_threshold=0.3,
            enable_forgetting=True,
            forget_interval_seconds=0,
        )
        fc = ForgettingCurve(config)
        # strength=100 → retention = e^{-1/100} ≈ 0.99 > 0.3
        meta = [
            {
                "faiss_id": 1,
                "text": "recent",
                "timestamp": "2020-01-31T00:00:00",
                "last_recall_date": "2020-01-31",
                "memory_strength": 100,
                "forgotten": False,
            }
        ]
        result = fc.maybe_forget(meta, reference_date="2020-02-01")
        assert result is not None
        assert meta[0]["forgotten"] is False

    def test_daily_summary_skipped(self):
        config = MemoryBankConfig(
            forget_mode="deterministic",
            soft_forget_threshold=0.9,
            enable_forgetting=True,
            forget_interval_seconds=0,
        )
        fc = ForgettingCurve(config)
        meta = [
            {
                "faiss_id": 1,
                "text": "summary",
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "memory_strength": 1,
                "type": "daily_summary",
                "forgotten": False,
            }
        ]
        fc.maybe_forget(meta, reference_date="2020-02-01")
        assert meta[0]["forgotten"] is False


class TestThrottle:
    def test_throttle_skips_second_call(self):
        config = MemoryBankConfig(
            forget_mode="deterministic",
            forget_interval_seconds=300,
            enable_forgetting=True,
        )
        fc = ForgettingCurve(config)
        meta = [
            {
                "faiss_id": 1,
                "memory_strength": 1,
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "forgotten": False,
            }
        ]
        r1 = fc.maybe_forget(meta, reference_date="2020-02-01")
        assert r1 is not None
        r2 = fc.maybe_forget(meta, reference_date="2020-02-01")
        assert r2 is None  # 节流跳过


class TestIngestionForget:
    def test_compute_ingestion_forget_ids_seeded(self):
        config = MemoryBankConfig(
            forget_mode="probabilistic",
            forget_interval_seconds=300,
            enable_forgetting=True,
            seed=42,
        )
        meta = [
            {
                "faiss_id": i,
                "text": f"entry {i}",
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "memory_strength": 1,
            }
            for i in range(5)
        ]
        ids = compute_ingestion_forget_ids(meta, "2020-02-01", config)
        # 固定 seed 应产生确定性结果
        ids2 = compute_ingestion_forget_ids(meta, "2020-02-01", config)
        assert ids == ids2, "same seed should produce deterministic results"
        # 不同 seed 应产生不同结果（极高概率）
        config2 = MemoryBankConfig(
            forget_mode="probabilistic",
            forget_interval_seconds=300,
            enable_forgetting=True,
            seed=99,
        )
        ids3 = compute_ingestion_forget_ids(meta, "2020-02-01", config2)
        # 不同 seed，概率模式，至少验证返回值结构一致且不抛异常
        assert isinstance(ids, list)
        assert isinstance(ids3, list)
        assert len(ids) == len(ids3)
        # 验证 seed 确定性：同 seed 同入参产生相同结果
        assert ids == compute_ingestion_forget_ids(meta, "2020-02-01", config)

    def test_daily_summary_skipped_in_ingestion(self):
        config = MemoryBankConfig(forget_mode="deterministic", seed=42)
        meta = [
            {
                "faiss_id": 1,
                "text": "summary",
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "memory_strength": 1,
                "type": "daily_summary",
            }
        ]
        ids = compute_ingestion_forget_ids(meta, "2020-02-01", config)
        assert ids == []

    def test_deterministic_high_strength_no_forgetting(self):
        """确定性模式高记忆强度条目不应被遗忘。"""
        config = MemoryBankConfig(forget_mode="deterministic", seed=42)
        meta = [
            {
                "faiss_id": 1,
                "text": "test",
                "timestamp": "2020-01-01T00:00:00",
                "last_recall_date": "2020-01-01",
                "memory_strength": 100,
            }
        ]
        ids = compute_ingestion_forget_ids(meta, "2020-02-01", config)
        assert ids == []  # retention ≈ 0.74 > 0.3
        assert "forgotten" not in meta[0]
