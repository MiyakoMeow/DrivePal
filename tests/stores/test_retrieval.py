"""retrieval.py 纯函数单元测试。"""

import os
from datetime import UTC, datetime

import pytest

from app.memory.memory_bank.retrieval import (
    _INTERNAL_KEYS,
    CHUNK_SIZE_MAX,
    CHUNK_SIZE_MIN,
    DEFAULT_CHUNK_SIZE,
    _penalize_score,
    _word_in_text,
    apply_speaker_filter,
    clean_search_result,
    deduplicate_overlaps,
    get_effective_chunk_size,
    merge_neighbors,
    safe_memory_strength,
    strip_source_prefix,
    update_memory_strengths,
)


def _make_metadata(entries: list[dict]) -> list[dict]:
    defaults = {
        "text": "default text",
        "source": "2024-06-15",
        "speakers": [],
        "memory_strength": 1,
    }
    return [{**defaults, **e} for e in entries]


class TestStripSourcePrefix:
    def test_conversation_prefix(self):
        result = strip_source_prefix(
            "Conversation content on 2024-06-15:Hello world", "2024-06-15"
        )
        assert result == "Hello world"

    def test_summary_prefix(self):
        result = strip_source_prefix(
            "The summary of the conversation on 2024-06-15 is:short summary",
            "2024-06-15",
        )
        assert result == "short summary"

    def test_no_prefix_returns_original(self):
        assert strip_source_prefix("Hello world", "2024-06-15") == "Hello world"

    def test_wrong_date_no_match(self):
        text = "Conversation content on 2024-06-15:Hello"
        assert strip_source_prefix(text, "2024-06-16") == text


class TestSafeMemoryStrength:
    def test_valid_integer(self):
        assert safe_memory_strength(3) == 3.0

    def test_valid_float(self):
        assert safe_memory_strength(2.5) == 2.5

    def test_valid_string(self):
        assert safe_memory_strength("4.2") == 4.2

    def test_none_fallback(self):
        assert safe_memory_strength(None) == 1.0

    def test_nan_fallback(self):
        assert safe_memory_strength(float("nan")) == 1.0

    def test_inf_fallback(self):
        assert safe_memory_strength(float("inf")) == 1.0

    def test_negative_fallback(self):
        assert safe_memory_strength(-1) == 1.0

    def test_zero_fallback(self):
        assert safe_memory_strength(0) == 1.0

    def test_non_numeric_string_fallback(self):
        assert safe_memory_strength("abc") == 1.0


class TestGetEffectiveChunkSize:
    def test_few_entries_returns_default(self):
        popped = os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)
        try:
            meta = [{"text": "hello"}] * 5
            assert get_effective_chunk_size(meta) == DEFAULT_CHUNK_SIZE
        finally:
            if popped is not None:
                os.environ["MEMORYBANK_CHUNK_SIZE"] = popped

    def test_many_entries_uses_p90(self):
        popped = os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)
        try:
            meta = [{"text": "x" * n} for n in range(1, 101)]
            sz = get_effective_chunk_size(meta)
            assert sz == 270
        finally:
            if popped is not None:
                os.environ["MEMORYBANK_CHUNK_SIZE"] = popped

    def test_env_override(self):
        os.environ["MEMORYBANK_CHUNK_SIZE"] = "3000"
        try:
            assert get_effective_chunk_size([]) == 3000
        finally:
            os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)

    def test_env_override_clamped_min(self):
        os.environ["MEMORYBANK_CHUNK_SIZE"] = "50"
        try:
            assert get_effective_chunk_size([]) == CHUNK_SIZE_MIN
        finally:
            os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)

    def test_env_override_clamped_max(self):
        os.environ["MEMORYBANK_CHUNK_SIZE"] = "99999"
        try:
            assert get_effective_chunk_size([]) == CHUNK_SIZE_MAX
        finally:
            os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)

    def test_env_override_invalid_value_ignored(self):
        os.environ["MEMORYBANK_CHUNK_SIZE"] = "not_a_number"
        popped_env = os.environ.pop("MEMORYBANK_CHUNK_SIZE")
        try:
            meta = [{"text": "hello"}] * 5
            assert get_effective_chunk_size(meta) == DEFAULT_CHUNK_SIZE
        finally:
            if popped_env is not None:
                os.environ["MEMORYBANK_CHUNK_SIZE"] = popped_env


class TestMergeNeighbors:
    def test_single_result_no_merge(self):
        metadata = _make_metadata([{"text": "hello"}])
        results = [{"_meta_idx": 0, "score": 0.9, "source": "2024-06-15"}]
        merged = merge_neighbors(results, metadata, DEFAULT_CHUNK_SIZE)
        assert len(merged) == 1
        assert merged[0]["text"] == "hello"

    def test_same_source_consecutive_merged(self):
        metadata = _make_metadata(
            [
                {"text": "a"},
                {"text": "b"},
                {"text": "c"},
            ]
        )
        results = [
            {"_meta_idx": 0, "score": 0.9, "source": "2024-06-15"},
            {"_meta_idx": 1, "score": 0.8, "source": "2024-06-15"},
            {"_meta_idx": 2, "score": 0.7, "source": "2024-06-15"},
        ]
        merged = merge_neighbors(results, metadata, DEFAULT_CHUNK_SIZE)
        assert len(merged) == 1
        assert "\x00" in merged[0]["text"]

    def test_chunk_size_trim(self):
        long_text = "x" * 1000
        metadata = _make_metadata(
            [
                {"text": long_text},
                {"text": long_text},
                {"text": long_text},
            ]
        )
        results = [{"_meta_idx": 1, "score": 0.9, "source": "2024-06-15"}]
        merged = merge_neighbors(results, metadata, 1500)
        total_len = len(merged[0]["text"].replace("\x00", ""))
        assert total_len <= 1500 + len("\x00") * 2

    def test_empty_results(self):
        assert merge_neighbors([], [], DEFAULT_CHUNK_SIZE) == []

    def test_no_meta_idx_passthrough(self):
        results = [{"score": 0.5, "text": "orphan"}]
        merged = merge_neighbors(results, [{"text": "x"}], DEFAULT_CHUNK_SIZE)
        assert len(merged) == 1
        assert merged[0]["text"] == "orphan"


class TestDeduplicateOverlaps:
    def test_no_overlap_passthrough(self):
        results = [
            {
                "_merged_indices": [0, 1],
                "score": 0.9,
                "text": "a\x00b",
                "speakers": [],
                "memory_strength": 2,
            },
            {
                "_merged_indices": [3, 4],
                "score": 0.8,
                "text": "d\x00e",
                "speakers": [],
                "memory_strength": 1,
            },
        ]
        merged = deduplicate_overlaps(results)
        assert len(merged) == 2

    def test_shared_index_merged(self):
        results = [
            {
                "_merged_indices": [0, 1, 2],
                "score": 0.9,
                "text": "a\x00b\x00c",
                "speakers": [],
                "memory_strength": 2,
            },
            {
                "_merged_indices": [2, 3, 4],
                "score": 0.8,
                "text": "c\x00d\x00e",
                "speakers": [],
                "memory_strength": 1,
            },
        ]
        merged = deduplicate_overlaps(results)
        assert len(merged) == 1
        assert merged[0]["_merged_indices"] == [0, 1, 2, 3, 4]

    def test_single_merge_item_untouched(self):
        results = [
            {
                "_merged_indices": [0, 1, 2],
                "score": 0.9,
                "text": "a\x00b\x00c",
                "speakers": [],
                "memory_strength": 2,
            },
            {"score": 0.8, "text": "hello", "speakers": []},
        ]
        merged = deduplicate_overlaps(results)
        assert len(merged) == 2


class TestPenalizeScore:
    def test_positive_score(self):
        assert _penalize_score(1.0) == 0.75

    def test_negative_score(self):
        assert _penalize_score(-1.0) == pytest.approx(-1.25)

    def test_zero_score(self):
        assert _penalize_score(0.0) == 0.0

    def test_large_positive(self):
        assert _penalize_score(10.0) == 7.5

    def test_large_negative(self):
        assert _penalize_score(-4.0) == pytest.approx(-5.0)


class TestWordInText:
    def test_word_found(self):
        assert _word_in_text("seat", "I like seat 45") is True

    def test_word_not_found(self):
        assert _word_in_text("seat", "theseats are nice") is False

    def test_empty_word(self):
        assert _word_in_text("", "any text") is False

    def test_whitespace_word(self):
        assert _word_in_text("  ", "any text") is False

    def test_case_sensitive(self):
        assert _word_in_text("Gary", "Gary likes cars") is True


class TestApplySpeakerFilter:
    def test_no_match_no_penalty(self):
        results = [
            {"score": 1.0, "speakers": ["Gary"]},
            {"score": 0.8, "speakers": ["Patricia"]},
        ]
        out = apply_speaker_filter(results, "some topic", ["Gary", "Patricia"])
        assert out[0]["score"] == 1.0
        assert out[1]["score"] == 0.8

    def test_positive_score_penalized(self):
        results = [
            {"score": 1.0, "speakers": ["Gary"]},
            {"score": 0.8, "speakers": ["Patricia"]},
        ]
        out = apply_speaker_filter(results, "Gary likes seat", ["Gary", "Patricia"])
        assert out[0]["score"] == 1.0
        assert out[1]["score"] == pytest.approx(0.6)

    def test_negative_score_penalized(self):
        results = [
            {"score": -0.5, "speakers": ["Gary"]},
            {"score": -0.3, "speakers": ["Patricia"]},
        ]
        out = apply_speaker_filter(results, "Gary likes seat", ["Gary", "Patricia"])
        assert out[0]["score"] == pytest.approx(-0.5)
        assert out[1]["score"] == pytest.approx(-0.3 * 1.25)

    def test_no_speakers_in_results(self):
        results = [
            {"score": 1.0, "speakers": None},
        ]
        out = apply_speaker_filter(results, "Gary likes seat", ["Gary"])
        assert out[0]["score"] == pytest.approx(0.75)


class TestUpdateMemoryStrengths:
    def test_increment_strength(self):
        meta = [{"memory_strength": 1, "last_recall_date": "2024-01-01"}]
        results = [{"_meta_idx": 0, "score": 0.9}]
        updated = update_memory_strengths(results, meta, "2024-06-15")
        assert updated is True
        assert meta[0]["memory_strength"] == 2.0

    def test_updates_recall_date(self):
        meta = [{"memory_strength": 1, "last_recall_date": "2024-01-01"}]
        results = [{"_meta_idx": 0, "score": 0.9}]
        update_memory_strengths(results, meta, "2024-06-15")
        assert meta[0]["last_recall_date"] == "2024-06-15"

    def test_no_changes_returns_false(self):
        meta = [{"memory_strength": 1}]
        results = []
        assert update_memory_strengths(results, meta, "2024-06-15") is False

    def test_all_meta_indices(self):
        meta = [
            {"memory_strength": 1, "last_recall_date": "2024-01-01"},
            {"memory_strength": 2, "last_recall_date": "2024-01-01"},
        ]
        results = [{"_all_meta_indices": [0, 1], "score": 0.9}]
        update_memory_strengths(results, meta, "2024-06-15")
        assert meta[0]["memory_strength"] == 2.0
        assert meta[1]["memory_strength"] == 3.0

    def test_no_reference_date_uses_today(self):
        meta = [{"memory_strength": 1}]
        results = [{"_meta_idx": 0}]
        update_memory_strengths(results, meta, None)

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert meta[0]["last_recall_date"] == today


class TestCleanSearchResult:
    def test_removes_internal_keys(self):
        r = {
            "_merged_indices": [0, 1],
            "_all_meta_indices": [0],
            "_meta_idx": 0,
            "faiss_id": 1,
            "text": "hello",
            "score": 0.9,
        }
        clean_search_result(r)
        for key in _INTERNAL_KEYS:
            assert key not in r
        assert "text" in r
        assert "score" in r

    def test_decodes_delimiter(self):
        r = {"text": "part1\x00part2\x00part3", "score": 0.9}
        clean_search_result(r)
        assert r["text"] == "part1; part2; part3"

    def test_no_delimiter_unchanged(self):
        r = {"text": "hello world", "score": 0.9}
        clean_search_result(r)
        assert r["text"] == "hello world"

    def test_missing_text_no_error(self):
        r = {"score": 0.9}
        clean_search_result(r)
        assert "text" not in r
