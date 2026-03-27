"""文本嵌入模型封装，基于HuggingFace模型."""

from langchain_huggingface import HuggingFaceEmbeddings


class EmbeddingModel:

    """HuggingFace文本嵌入模型封装."""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", device: str = "cpu"):
        """初始化嵌入模型."""
        self.model_name = model_name
        self.device = device
        self._client = None

    @property
    def client(self) -> HuggingFaceEmbeddings:
        """获取或延迟创建HuggingFace嵌入模型客户端."""
        if self._client is None:
            try:
                self._client = HuggingFaceEmbeddings(
                    model_name=self.model_name,
                    model_kwargs={"device": self.device},
                    encode_kwargs={"normalize_embeddings": True},
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load embedding model '{self.model_name}': {type(e).__name__}"
                ) from e
        return self._client

    def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        embeddings = self.client.embed_query(text)
        if isinstance(embeddings, list):
            return embeddings  # type: ignore[return-value]
        return list(embeddings)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码."""
        embeddings = self.client.embed_documents(texts)
        return [list(emb) if not isinstance(emb, list) else emb for emb in embeddings]
