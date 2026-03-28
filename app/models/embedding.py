"""文本嵌入模型封装，支持 HuggingFace 本地模型和 OpenAI 兼容远程接口."""

from typing import Any

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
        """初始化嵌入模型."""
        if providers is None:
            try:
                settings = LLMSettings.load()
                providers = settings.embedding_providers
            except RuntimeError:
                if device is not None:
                    providers = [
                        EmbeddingProviderConfig(
                            model="BAAI/bge-small-zh-v1.5", device=device
                        )
                    ]
                else:
                    raise
        self.providers = providers
        self.device = device
        self._client = None

    @property
    def client(self):
        """获取或延迟创建嵌入模型客户端，按 provider 顺序尝试."""
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
            kwargs: dict[str, Any] = {"model": provider.model}
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
        """编码文本为向量."""
        embeddings = self.client.embed_query(text)
        if isinstance(embeddings, list):
            return embeddings
        return list(embeddings)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码."""
        embeddings = self.client.embed_documents(texts)
        return [list(emb) if not isinstance(emb, list) else emb for emb in embeddings]
