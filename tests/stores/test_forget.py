"""ForgettingCurve 单元测试。"""

import random
from datetime import UTC, datetime

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.forget import (
    ForgettingCurve,
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


class TestForgettingCurve:
    """遗忘曲线判定逻辑测试。"""

    def test_fresh_curve_no_forget(self):
        """验证新条目不被遗忘。"""
        fc = ForgettingCurve(MemoryBankConfig(forget_mode="deterministic"))
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 5,
                "timestamp": "2026-05-05T00:00:00",
                "last_recall_date": "2026-05-05",
            }
        ]
        fc.maybe_forget(entries, reference_date="2026-05-05")
        assert entries[0].get("forgotten") is None

    def test_old_entry_marked_forgotten(self):
        """验证旧条目被标记遗忘。"""
        fc = ForgettingCurve(MemoryBankConfig(forget_mode="deterministic"))
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "last_recall_date": "2026-01-01",
            }
        ]
        fc.maybe_forget(entries, reference_date="2026-05-05")
        assert entries[0].get("forgotten") is True

    def test_daily_summary_exempt(self):
        """验证每日摘要不被遗忘。"""
        fc = ForgettingCurve(MemoryBankConfig(forget_mode="deterministic"))
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "type": "daily_summary",
            }
        ]
        fc.maybe_forget(entries, reference_date="2026-05-05")
        assert entries[0].get("forgotten") is None

    def test_throttle_skips_second_call(self):
        """验证节流机制跳过短时间内重复遗忘（返回 None）。"""
        fc = ForgettingCurve(MemoryBankConfig(forget_mode="deterministic"))
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "last_recall_date": "2026-01-01",
            }
        ]
        result = fc.maybe_forget(entries, reference_date="2026-05-05")
        assert result is not None  # 首次调用应执行
        assert entries[0].get("forgotten") is True
        entries[0]["forgotten"] = False
        result = fc.maybe_forget(entries, reference_date="2026-05-05")
        assert result is None  # 节流，未执行
        assert entries[0].get("forgotten") is False


class TestProbabilisticForgetting:
    """概率性遗忘模式测试。"""

    def test_probabilistic_maybe_forget_returns_ids(self):
        """概率模式下 maybe_forget 返回被遗忘条目的 FAISS ID。"""
        config = MemoryBankConfig(forget_mode="probabilistic", seed=42)
        fc = ForgettingCurve(config)
        entries = [
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
        ids = fc.maybe_forget(entries, reference_date="2026-05-05")
        assert ids is not None
        # 第一条 strength=1, 125天 → retention≈0, 必遗忘
        assert 0 in ids
        assert entries[0].get("forgotten") is True

    def test_deterministic_returns_empty_ids(self):
        """确定性模式 maybe_forget 返回空列表。"""
        fc = ForgettingCurve(MemoryBankConfig(forget_mode="deterministic"))
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "last_recall_date": "2026-01-01",
            },
        ]
        ids = fc.maybe_forget(entries, reference_date="2026-05-05")
        assert ids == []

    def test_summary_exempt_in_probabilistic(self):
        """概率模式下每日摘要豁免遗忘。"""
        config = MemoryBankConfig(forget_mode="probabilistic", seed=42)
        fc = ForgettingCurve(config)
        entries = [
            {
                "faiss_id": 0,
                "memory_strength": 1,
                "timestamp": "2026-01-01T00:00:00",
                "type": "daily_summary",
            },
        ]
        ids = fc.maybe_forget(entries, reference_date="2026-05-05")
        assert ids == []

    def test_probabilistic_reproducible_with_seed(self):
        """固定 seed 产生可复现的遗忘结果。"""
        config1 = MemoryBankConfig(forget_mode="probabilistic", seed=42)
        config2 = MemoryBankConfig(forget_mode="probabilistic", seed=42)
        fc1 = ForgettingCurve(config1)
        fc2 = ForgettingCurve(config2)
        entries1 = [
            {
                "faiss_id": i,
                "memory_strength": 2,
                "timestamp": "2026-03-01T00:00:00",
                "last_recall_date": "2026-03-01",
            }
            for i in range(20)
        ]
        entries2 = [
            {
                "faiss_id": i,
                "memory_strength": 2,
                "timestamp": "2026-03-01T00:00:00",
                "last_recall_date": "2026-03-01",
            }
            for i in range(20)
        ]
        ids1 = fc1.maybe_forget(entries1, reference_date="2026-05-05")
        ids2 = fc2.maybe_forget(entries2, reference_date="2026-05-05")
        assert ids1 == ids2

    def test_external_rng_consistent_with_internal_seed(self):
        """外部传入 RNG 与同 seed 内部构造 RNG 行为一致。"""
        rng = random.Random(42)
        config_ext = MemoryBankConfig(forget_mode="probabilistic")
        config_int = MemoryBankConfig(forget_mode="probabilistic", seed=42)
        fc_ext = ForgettingCurve(config_ext, rng=rng)
        fc_int = ForgettingCurve(config_int)
        entries_ext = [
            {
                "faiss_id": i,
                "memory_strength": 2,
                "timestamp": "2026-03-01T00:00:00",
                "last_recall_date": "2026-03-01",
            }
            for i in range(20)
        ]
        entries_int = [
            {
                "faiss_id": i,
                "memory_strength": 2,
                "timestamp": "2026-03-01T00:00:00",
                "last_recall_date": "2026-03-01",
            }
            for i in range(20)
        ]
        ids_ext = fc_ext.maybe_forget(entries_ext, reference_date="2026-05-05")
        ids_int = fc_int.maybe_forget(entries_int, reference_date="2026-05-05")
        assert ids_ext == ids_int


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
            config=MemoryBankConfig(forget_mode="deterministic"),
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
            config=MemoryBankConfig(forget_mode="deterministic"),
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
        config = MemoryBankConfig(forget_mode="probabilistic")
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        ids_a = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            config=config,
            rng=rng_a,
        )
        ids_b = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            config=config,
            rng=rng_b,
        )
        assert ids_a == ids_b


class TestForgetBoundaries:
    """遗忘边界条件测试。"""

    def test_compute_ingestion_deterministic_threshold(self):
        """确定性模式 compute_ingestion_forget_ids 用 0.3 阈值判定。"""
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            },
        ]
        # strength=1, ~165天, retention≈e^(-165/1)≈0 → <0.3 → 应遗忘
        ids = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            config=MemoryBankConfig(forget_mode="deterministic"),
        )
        assert 0 in ids

    def test_ingestion_skip_corrupted_date(self):
        """格式错误的日期条目被跳过。"""
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "invalid-date",
                "timestamp": "invalid-date",
                "memory_strength": 1,
            },
            {
                "faiss_id": 1,
                "last_recall_date": "2024-06-10",
                "timestamp": "2024-06-10T00:00:00",
                "memory_strength": 5,
            },
        ]
        ids = compute_ingestion_forget_ids(
            metadata,
            "2024-06-15",
            config=MemoryBankConfig(forget_mode="deterministic"),
        )
        assert 0 not in ids  # 格式错误跳过
        assert 1 not in ids  # 近期条目保留
