"""文本嵌入模型封装，支持 HuggingFace 本地模型和 OpenAI 兼容远程接口."""

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings

from app.models.settings import EmbeddingProviderConfig, LLMSettings


class EmbeddingModel:
    """文本嵌入模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[EmbeddingProviderConfig] | None = None,
        device: str | None = None,
    ):
        if providers is None:
            settings = LLMSettings.load()
            providers = settings.embedding_providers
        self.providers = providers
        self.device = device
        self._client = None

    @property
    def client(self):
        if self._client is not None:
            return self._client

        if not self.providers:
            raise RuntimeError("No embedding providers configured")

        errors = []
        for provider in self.providers:
            try:
                self._client = self._create_client(provider)
                return self._client
            except Exception as e:
                errors.append(f"{provider.model}: {e}")
                continue

        raise RuntimeError(f"All embedding providers failed: {'; '.join(errors)}")

    def _create_client(self, provider: EmbeddingProviderConfig):
        device = self.device or provider.device
        if provider.base_url:
            kwargs = {"model": provider.model}
            if provider.api_key:
                from langchain_core.utils.utils import SecretStr

                kwargs["openai_api_key"] = SecretStr(provider.api_key)
            kwargs["openai_api_base"] = provider.base_url
            return OpenAIEmbeddings(**kwargs)
        return HuggingFaceEmbeddings(
            model_name=provider.model,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )

    def encode(self, text: str) -> list[float]:
        embeddings = self.client.embed_query(text)
        if isinstance(embeddings, list):
            return embeddings
        return list(embeddings)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.client.embed_documents(texts)
        return [list(emb) if not isinstance(emb, list) else emb for emb in embeddings]
