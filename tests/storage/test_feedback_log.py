"""反馈日志存储测试."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.storage.feedback_log import aggregate_weights, append_feedback

if TYPE_CHECKING:
    from pathlib import Path


async def test_feedback_log_append_and_aggregate(tmp_path: Path) -> None:
    """验证反馈日志追加写和权重聚合."""
    u_dir = tmp_path / "users" / "default"
    u_dir.mkdir(parents=True, exist_ok=True)

    await append_feedback(u_dir, "e1", "accept", "meeting")
    await append_feedback(u_dir, "e2", "accept", "meeting")
    await append_feedback(u_dir, "e3", "ignore", "meeting")

    weights = await aggregate_weights(u_dir)
    assert "meeting" in weights
    assert weights["meeting"] == pytest.approx(0.6)


async def test_feedback_log_clamp(tmp_path: Path) -> None:
    """验证权重 clamp 到 [0.1, 1.0]."""
    u_dir = tmp_path / "users" / "default"
    u_dir.mkdir(parents=True, exist_ok=True)

    for i in range(10):
        await append_feedback(u_dir, f"e{i}", "ignore", "weather")

    weights = await aggregate_weights(u_dir)
    assert weights["weather"] == pytest.approx(0.1)
