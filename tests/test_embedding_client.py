"""EmbeddingClient 单元测试."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.memory.embedding_client import EmbeddingClient

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


if TYPE_CHECKING:
    _Base = EmbeddingModel
else:
    _Base = object


class _FakeEmbeddingModel(_Base):
    def __init__(self) -> None:
        self.call_count = 0
        self.fail_count = 0
        self.fail_pattern: str | None = None

    async def encode(self, text: str) -> list[float]:
        self.call_count += 1
        if self.fail_count > 0:
            self.fail_count -= 1
            msg = f"{self.fail_pattern or 'connection'} error"
            raise RuntimeError(msg)
        return [0.1, 0.2, 0.3]


async def test_encode_success_first_try() -> None:
    """Encode 首次成功无重试."""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == [0.1, 0.2, 0.3]
    assert model.call_count == 1


async def test_encode_retry_on_transient_error() -> None:
    """瞬态错误后重试直至成功."""
    model = _FakeEmbeddingModel()
    model.fail_count = 2
    model.fail_pattern = "timeout"
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == [0.1, 0.2, 0.3]
    assert model.call_count == 3


async def test_encode_retry_exhausted() -> None:
    """重试耗尽后抛出."""
    model = _FakeEmbeddingModel()
    model.fail_count = 10
    model.fail_pattern = "connection"
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError):
        await client.encode("hello")
    assert model.call_count == EmbeddingClient.MAX_RETRIES


async def test_encode_non_transient_fast_fail() -> None:
    """非瞬态错误不重试."""
    model = _FakeEmbeddingModel()
    model.fail_pattern = "invalid api key"
    model.fail_count = 1
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError):
        await client.encode("hello")
    assert model.call_count == 1


async def test_encode_batch() -> None:
    """encode_batch 分批编码."""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    results = await client.encode_batch(["a", "b"])
    assert len(results) == 2
    assert results[0] == [0.1, 0.2, 0.3]


async def test_encode_batch_multiple_batches() -> None:
    """150 条文本跨 2 批（100+50）."""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    texts = [str(i) for i in range(150)]
    results = await client.encode_batch(texts)
    assert len(results) == 150
    assert all(r == [0.1, 0.2, 0.3] for r in results)
