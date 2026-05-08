import math
import random
from datetime import UTC, datetime

import pytest

from app.memory.memory_bank.forget import (
    ForgetMode,
    compute_forget_ids,
    compute_reference_date,
    forgetting_retention,
)


class TestForgettingRetention:
    def test_zero_days_returns_one(self):
        assert forgetting_retention(0, 1) == pytest.approx(1.0)

    def test_negative_days_returns_one(self):
        assert forgetting_retention(-1, 1) == pytest.approx(1.0)

    def test_zero_strength_returns_zero(self):
        assert forgetting_retention(1, 0) == pytest.approx(0.0)

    def test_negative_strength_returns_zero(self):
        assert forgetting_retention(1, -1) == pytest.approx(0.0)

    def test_decay_trend(self):
        assert forgetting_retention(1, 1) > forgetting_retention(10, 1)
        assert forgetting_retention(5, 5) > forgetting_retention(5, 1)

    def test_known_value(self):
        assert forgetting_retention(10, 5) == pytest.approx(math.exp(-2))


class TestComputeForgetIds:
    def test_deterministic_below_threshold(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            },
        ]
        ids = compute_forget_ids(metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC)
        assert 0 in ids

    def test_deterministic_above_threshold(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-06-14",
                "timestamp": "2024-06-14T00:00:00",
                "memory_strength": 5,
            },
        ]
        ids = compute_forget_ids(metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC)
        assert 0 not in ids

    def test_skips_daily_summary(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
                "type": "daily_summary",
            },
        ]
        ids = compute_forget_ids(metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC)
        assert ids == []

    def test_probabilistic_with_seed(self):
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
        ids_a = compute_forget_ids(
            metadata, "2024-06-15", mode=ForgetMode.PROBABILISTIC, rng=rng_a
        )
        ids_b = compute_forget_ids(
            metadata, "2024-06-15", mode=ForgetMode.PROBABILISTIC, rng=rng_b
        )
        assert ids_a == ids_b

    def test_invalid_date_entry_preserved(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "not-a-date",
                "timestamp": "also-invalid",
                "memory_strength": 1,
            },
        ]
        ids = compute_forget_ids(metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC)
        assert ids == []

    def test_invalid_reference_date_returns_empty(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "memory_strength": 1,
            },
        ]
        ids = compute_forget_ids(metadata, "not-a-date", mode=ForgetMode.DETERMINISTIC)
        assert ids == []

    def test_does_not_modify_metadata(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            },
        ]
        original = [dict(e) for e in metadata]
        compute_forget_ids(metadata, "2024-06-15")
        assert metadata == original

    def test_no_faiss_id_skipped(self):
        metadata = [
            {
                "last_recall_date": "2024-01-01",
                "timestamp": "2024-01-01T00:00:00",
                "memory_strength": 1,
            },
        ]
        ids = compute_forget_ids(metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC)
        assert ids == []

    def test_custom_threshold(self):
        metadata = [
            {
                "faiss_id": 0,
                "last_recall_date": "2024-06-14",
                "timestamp": "2024-06-14T00:00:00",
                "memory_strength": 5,
            },
        ]
        ids_default = compute_forget_ids(
            metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC, threshold=0.15
        )
        ids_high = compute_forget_ids(
            metadata, "2024-06-15", mode=ForgetMode.DETERMINISTIC, threshold=0.99
        )
        assert 0 not in ids_default
        assert 0 in ids_high


class TestComputeReferenceDate:
    def test_basic(self):
        metadata = [
            {"timestamp": "2024-06-10T00:00:00"},
            {"timestamp": "2024-06-14T00:00:00"},
            {"timestamp": "2024-06-12T00:00:00"},
        ]
        assert compute_reference_date(metadata) == "2024-06-15"

    def test_empty_metadata(self):
        result = compute_reference_date([])
        expected = datetime.now(UTC).strftime("%Y-%m-%d")
        assert result == expected

    def test_uses_last_recall_date(self):
        metadata = [
            {"timestamp": "2024-06-10T00:00:00", "last_recall_date": "2024-06-13"},
        ]
        assert compute_reference_date(metadata) == "2024-06-14"

    def test_all_invalid_dates(self):
        metadata = [
            {"timestamp": "bad"},
            {"timestamp": "also-bad"},
        ]
        result = compute_reference_date(metadata)
        expected = datetime.now(UTC).strftime("%Y-%m-%d")
        assert result == expected
