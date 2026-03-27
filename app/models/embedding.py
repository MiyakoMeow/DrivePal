from langchain_huggingface import HuggingFaceEmbeddings


class EmbeddingModel:
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._client = None

    @property
    def client(self) -> HuggingFaceEmbeddings:
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
        """编码文本为向量"""
        embeddings = self.client.embed_query(text)
        if isinstance(embeddings, list):
            return embeddings  # type: ignore[return-value]
        return list(embeddings)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码"""
        embeddings = self.client.embed_documents(texts)
        return [list(emb) if not isinstance(emb, list) else emb for emb in embeddings]
