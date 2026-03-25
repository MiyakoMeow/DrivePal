from langchain_community.embeddings import HuggingFaceBgeEmbeddings


class EmbeddingModel:
    def __init__(self, model_name: str = "bge-small-zh-v1.5", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._client = None

    @property
    def client(self) -> HuggingFaceBgeEmbeddings:
        if self._client is None:
            self._client = HuggingFaceBgeEmbeddings(
                model_name=self.model_name,
                model_kwargs={"device": self.device},
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._client

    def encode(self, text: str) -> list[float]:
        """编码文本为向量"""
        return self.client.embed_query(text)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码"""
        return self.client.embed_documents(texts)
