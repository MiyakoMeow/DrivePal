"""记忆模块共享工具函数."""

import logging

logger = logging.getLogger(__name__)


def cosine_similarity(a: list, b: list) -> float:
    """计算两个向量的余弦相似度."""
    if len(a) != len(b):
        min_len = min(len(a), len(b))
        logger.warning(
            "向量长度不一致 (%d vs %d)，截断到 %d 维计算",
            len(a),
            len(b),
            min_len,
        )
        a = a[:min_len]
        b = b[:min_len]
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0
