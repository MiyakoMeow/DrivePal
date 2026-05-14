"""Append-only 反馈日志，聚合权重计算."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.storage.jsonl_store import JSONLinesStore

if TYPE_CHECKING:
    from pathlib import Path


def feedback_log_store(user_dir: Path) -> JSONLinesStore:
    """获取反馈日志存储实例."""
    return JSONLinesStore(user_dir=user_dir, filename="feedback_log.jsonl")


async def append_feedback(
    user_dir: Path,
    event_id: str,
    action: str,
    feedback_type: str,
) -> None:
    """追加一条反馈记录."""
    store = feedback_log_store(user_dir)
    await store.append({
        "event_id": event_id,
        "action": action,
        "type": feedback_type,
        "timestamp": datetime.now(UTC).isoformat(),
    })


async def aggregate_weights(user_dir: Path) -> dict[str, float]:
    """从反馈日志聚合各类型权重。

    基础权重 0.5，每条 accept +0.1，每条 ignore -0.1。
    结果 clamp 到 [0.1, 1.0]。
    """
    store = feedback_log_store(user_dir)
    records = await store.read_all()
    counts: dict[str, float] = {}
    for rec in records:
        t = rec.get("type", "")
        if not t:
            continue
        delta = 0.1 if rec.get("action") == "accept" else -0.1
        counts[t] = counts.get(t, 0.0) + delta
    return {t: max(0.1, min(1.0, 0.5 + delta)) for t, delta in counts.items()}
