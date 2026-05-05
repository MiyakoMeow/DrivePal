"""ForgettingCurve 单元测试。"""

import pytest

from app.memory.stores.memory_bank.forget import (
    ForgettingCurve,
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
        fc = ForgettingCurve()
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
        fc = ForgettingCurve()
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
        fc = ForgettingCurve()
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
        """验证节流机制跳过短时间内重复遗忘。"""
        fc = ForgettingCurve()
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
        entries[0]["forgotten"] = False
        fc.maybe_forget(entries, reference_date="2026-05-05")
        assert entries[0].get("forgotten") is False  # 节流，未执行遗忘
