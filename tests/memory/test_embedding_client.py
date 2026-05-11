"""EmbeddingClient 单元测试。"""

from unittest.mock import AsyncMock

import pytest

from app.memory.embedding_client import EmbeddingClient


async def test_encode_delegates_to_model() -> None:
    """Encode 直接委托 EmbeddingModel.encode。"""
    model = AsyncMock()
    model.encode.return_value = [0.1, 0.2, 0.3]
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == [0.1, 0.2, 0.3]
    model.encode.assert_awaited_once_with("hello")


async def test_encode_batch_delegates_to_model() -> None:
    """encode_batch 委托 EmbeddingModel.batch_encode。"""
    model = AsyncMock()
    model.batch_encode = AsyncMock(return_value=[[0.1] * 4, [0.2] * 4])
    client = EmbeddingClient(model)
    results = await client.encode_batch(["a", "b"])
    assert results == [[0.1] * 4, [0.2] * 4]
    model.batch_encode.assert_awaited_once_with(["a", "b"])


async def test_encode_batch_empty_returns_empty() -> None:
    """空输入直接返回空列表，不调用模型。"""
    model = AsyncMock()
    client = EmbeddingClient(model)
    assert await client.encode_batch([]) == []
    model.batch_encode.assert_not_awaited()


async def test_encode_batch_dimension_mismatch_raises() -> None:
    """返回向量维度不一致时抛出 RuntimeError。"""
    model = AsyncMock()
    model.batch_encode = AsyncMock(return_value=[[0.1] * 4, [0.2] * 8])
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        await client.encode_batch(["a", "b"])
