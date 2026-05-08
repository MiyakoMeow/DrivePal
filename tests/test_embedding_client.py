"""EmbeddingClient 单元测试."""

from __future__ import annotations

import random as rng_mod
from typing import TYPE_CHECKING

import pytest

from app.memory.embedding_client import EmbeddingClient

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


if TYPE_CHECKING:
    _Base = EmbeddingModel
else:
    _Base = object


_VEC = [0.1, 0.2, 0.3]


class _FakeEmbeddingModel(_Base):
    """模拟 EmbeddingModel，支持 encode 和 batch_encode。"""

    def __init__(self) -> None:
        self.encode_calls: list[str] = []
        self.batch_calls: list[list[str]] = []
        self.fail_count = 0
        self.fail_pattern: str | None = None

    async def encode(self, text: str) -> list[float]:
        self.encode_calls.append(text)
        return self._maybe_raise() or _VEC

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        self._maybe_raise()
        return [_VEC] * len(texts)

    def _maybe_raise(self) -> None:
        if self.fail_count > 0:
            self.fail_count -= 1
            msg = f"{self.fail_pattern or 'connection'} error"
            raise RuntimeError(msg)


class _FakeNoBatchModel(_Base):
    """无 batch_encode 的退化模型。"""

    def __init__(self) -> None:
        self.encode_calls: list[str] = []

    async def encode(self, text: str) -> list[float]:
        self.encode_calls.append(text)
        return _VEC


class _FakeBatchOnlyModel(_Base):
    """仅有 batch_encode 的模型。"""

    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [_VEC] * len(texts)


async def _noop_sleep(_: float) -> None:
    return None


async def test_encode_delegates_to_encode_batch() -> None:
    """encode 委托给 encode_batch，走 batch_encode 路径。"""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == _VEC
    assert model.batch_calls == [["hello"]]
    assert model.encode_calls == []


async def test_encode_batch_success() -> None:
    """encode_batch 走 batch_encode 路径。"""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    results = await client.encode_batch(["a", "b", "c"])
    assert results == [_VEC, _VEC, _VEC]
    assert model.batch_calls == [["a", "b", "c"]]
    assert model.encode_calls == []


async def test_encode_batch_empty() -> None:
    """空列表直接返回空。"""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    assert await client.encode_batch([]) == []
    assert model.batch_calls == []


async def test_encode_batch_splits_into_batches() -> None:
    """150 条文本跨 2 批（100+50）。"""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    texts = [str(i) for i in range(150)]
    results = await client.encode_batch(texts)
    assert len(results) == 150
    assert all(r == _VEC for r in results)
    assert len(model.batch_calls) == 2
    assert len(model.batch_calls[0]) == 100
    assert len(model.batch_calls[1]) == 50


async def test_encode_batch_retry_on_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    """瞬态错误后重试直至成功。"""
    monkeypatch.setattr("app.memory.embedding_client._SLEEP", _noop_sleep)
    model = _FakeEmbeddingModel()
    model.fail_count = 2
    model.fail_pattern = "timeout"
    client = EmbeddingClient(model)
    results = await client.encode_batch(["a", "b"])
    assert results == [_VEC, _VEC]
    assert len(model.batch_calls) == 3


async def test_encode_batch_retry_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试耗尽后抛出。"""
    monkeypatch.setattr("app.memory.embedding_client._SLEEP", _noop_sleep)
    model = _FakeEmbeddingModel()
    model.fail_count = 10
    model.fail_pattern = "connection"
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError, match="connection"):
        await client.encode_batch(["a"])
    assert len(model.batch_calls) == EmbeddingClient.MAX_RETRIES


async def test_encode_batch_non_transient_fast_fail() -> None:
    """非瞬态错误不重试。"""
    model = _FakeEmbeddingModel()
    model.fail_pattern = "invalid api key"
    model.fail_count = 1
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError, match="invalid api key"):
        await client.encode_batch(["a"])
    assert len(model.batch_calls) == 1


async def test_fallback_to_encode_when_no_batch() -> None:
    """无 batch_encode 时退化逐条 encode。"""
    model = _FakeNoBatchModel()
    client = EmbeddingClient(model)
    results = await client.encode_batch(["x", "y"])
    assert results == [_VEC, _VEC]
    assert model.encode_calls == ["x", "y"]


async def test_batch_only_model() -> None:
    """仅 batch_encode 的模型正常工作。"""
    model = _FakeBatchOnlyModel()
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == _VEC
    assert model.batch_calls == [["hello"]]


async def test_backoff_delay_with_rng(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证退避延迟使用 rng 产生 jitter。"""
    delays: list[float] = []

    async def mock_sleep(d: float) -> None:
        delays.append(d)

    monkeypatch.setattr("app.memory.embedding_client._SLEEP", mock_sleep)
    fake_rng = rng_mod.Random(42)
    model = _FakeEmbeddingModel()
    model.fail_count = 3
    model.fail_pattern = "rate limit"
    client = EmbeddingClient(model, rng=fake_rng)
    await client.encode_batch(["a"])
    assert len(delays) == 3
    assert all(0 < d <= 10.5 for d in delays)
    assert delays[0] < delays[1] < delays[2]
