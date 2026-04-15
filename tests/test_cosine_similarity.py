"""cosine_similarity 测试."""

import logging

import pytest

from app.memory.utils import cosine_similarity


class TestCosineSimilarity:
    """cosine_similarity 测试."""

    def test_identical_vectors(self):
        """相同向量返回 1.0."""
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """正交向量返回 0.0."""
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_zero_vector(self):
        """零向量返回 0.0."""
        assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    def test_mismatched_lengths_truncates_with_warning(self, caplog):
        """长度不一致时截断计算并记录 warning."""
        with caplog.at_level(logging.WARNING, logger="app.memory.utils"):
            result = cosine_similarity([1, 0, 1], [1, 0])
        assert result == pytest.approx(1.0)
        assert "向量长度不一致" in caplog.text

    def test_mismatched_lengths_calculation_correct(self, caplog):
        """截断后 dot、norm_a、norm_b 都基于截断后的子向量计算."""
        with caplog.at_level(logging.WARNING, logger="app.memory.utils"):
            result = cosine_similarity([3, 4, 5], [3, 4])
        assert result == pytest.approx(1.0)

    def test_same_length_no_warning(self, caplog):
        """相同长度时不记录 warning."""
        with caplog.at_level(logging.WARNING, logger="app.memory.utils"):
            cosine_similarity([1, 2, 3], [4, 5, 6])
        assert "向量长度不一致" not in caplog.text
