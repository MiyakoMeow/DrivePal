"""文本嵌入模型封装，支持 HuggingFace 本地模型和 OpenAI 兼容远程接口."""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

import openai

from app.models.settings import EmbeddingProviderConfig, LLMSettings, ProviderConfig

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_EMBEDDING_MODEL_CACHE: dict[str, EmbeddingModel] = {}


def get_cached_embedding_model(device: str | None = None) -> EmbeddingModel:
    """获取缓存的embedding模型实例，避免重复加载."""
    cache_key = f"device={device or 'default'}"
    if cache_key not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(device=device)
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """清除embedding模型缓存."""
    _EMBEDDING_MODEL_CACHE.clear()


class EmbeddingModel:
    """文本嵌入模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[EmbeddingProviderConfig] | None = None,
        device: str | None = None,
    ) -> None:
        """初始化嵌入模型."""
        if providers is None:
            try:
                settings = LLMSettings.load()
                providers = settings.embedding_providers
            except RuntimeError:
                providers = [
                    EmbeddingProviderConfig(
                        provider=ProviderConfig(model="BAAI/bge-small-zh-v1.5"),
                        device=device or "cpu",
                    )
                ]
        self.providers = providers
        self.device = device
        self._client: Union[openai.AsyncOpenAI, SentenceTransformer, None] = None
        self._active_provider: EmbeddingProviderConfig | None = None

    @property
    def client(self) -> Union[openai.AsyncOpenAI, SentenceTransformer]:
        """获取或延迟创建嵌入模型客户端，按provider顺序尝试."""
        if self._client is not None:
            return self._client

        if not self.providers:
            raise RuntimeError("No embedding providers configured")

        errors = []
        for provider in self.providers:
            try:
                self._client = self._create_client(provider)
                self._active_provider = provider
                return self._client
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise RuntimeError(f"All embedding providers failed: {'; '.join(errors)}")

    def _create_client(
        self,
        provider: EmbeddingProviderConfig,
    ) -> Union[openai.AsyncOpenAI, SentenceTransformer]:
        """创建嵌入模型客户端."""
        device = self.device or provider.device
        if provider.provider.base_url:
            kwargs: dict = {"api_key": provider.provider.api_key or "not-needed"}
            kwargs["base_url"] = provider.provider.base_url
            return openai.AsyncOpenAI(**kwargs)
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(
            provider.provider.model,
            device=device,
        )

    async def _async_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        text: str,
    ) -> list[float]:
        """使用openai异步接口编码文本."""
        resp = await client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    def _encode_with_local(
        self,
        model: SentenceTransformer,
        text: str,
    ) -> list[float]:
        """使用本地模型编码文本."""
        return model.encode(text, normalize_embeddings=True).tolist()

    async def _async_batch_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """使用openai异步接口批量编码文本."""
        resp = await client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]

    def _batch_encode_with_local(
        self,
        model: SentenceTransformer,
        texts: list[str],
    ) -> list[list[float]]:
        """使用本地模型批量编码文本."""
        embeddings = model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    def _active_provider_or_raise(self) -> EmbeddingProviderConfig:
        if self._active_provider is not None:
            return self._active_provider
        if self.providers:
            self._active_provider = self.providers[0]
            return self._active_provider
        raise RuntimeError("No embedding providers configured")

    async def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        cl = self.client
        provider = self._active_provider_or_raise()
        if isinstance(cl, openai.AsyncOpenAI):
            return await self._async_encode_with_openai(
                cl, provider.provider.model, text
            )
        return self._encode_with_local(cl, text)

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本为向量."""
        cl = self.client
        provider = self._active_provider_or_raise()
        if isinstance(cl, openai.AsyncOpenAI):
            return await self._async_batch_encode_with_openai(
                cl, provider.provider.model, texts
            )
        return self._batch_encode_with_local(cl, texts)
