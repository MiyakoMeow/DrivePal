"""记忆模块共享工具函数."""


def cosine_similarity(a: list, b: list) -> float:
    """计算两个向量的余弦相似度."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0
