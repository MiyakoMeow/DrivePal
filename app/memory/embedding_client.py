"""EmbeddingModel 薄代理，添加维度一致性检测。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingClient:
    """EmbeddingModel 的薄代理，添加维度一致性检测。

    重试逻辑由 EmbeddingModel 内部处理（3 次指数退避），
    此处不再冗余重试。
    """

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        """初始化 EmbeddingClient。

        Args:
            embedding_model: 嵌入模型实例。

        """
        self._model = embedding_model

    async def encode(self, text: str) -> list[float]:
        """编码单条文本。"""
        return await self._model.encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码，使用 EmbeddingModel.batch_encode 并检测维度一致性。"""
        if not texts:
            return []
        results = await self._model.batch_encode(texts)
        if len(results) != len(texts):
            msg = (
                f"batch_encode returned {len(results)} embeddings "
                f"for {len(texts)} inputs"
            )
            raise RuntimeError(msg)
        dims = {len(v) for v in results}
        if len(dims) > 1:
            msg = f"Embedding dimension mismatch: {dims}. All vectors must have the same dimension."
            raise RuntimeError(msg)
        return results
