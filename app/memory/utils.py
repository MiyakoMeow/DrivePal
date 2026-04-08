"""记忆模块共享工具函数."""

from datetime import date


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0


def days_elapsed_since(last_recall: str, today: date) -> int:
    """计算从上次回忆到今天经过的天数."""
    try:
        last_date = date.fromisoformat(str(last_recall))
        return (today - last_date).days
    except ValueError, TypeError:
        return 0
