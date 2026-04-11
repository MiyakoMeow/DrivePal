"""文本嵌入模型封装，仅支持 OpenAI 兼容远程接口."""

import hashlib

import openai

from app.models._http import CLIENT_TIMEOUT as _CLIENT_TIMEOUT
from app.models.settings import EmbeddingProviderConfig, LLMSettings

_EMBEDDING_MODEL_CACHE: dict[str, EmbeddingModel] = {}


def get_cached_embedding_model() -> EmbeddingModel:
    """获取缓存的embedding模型实例，避免重复加载."""
    settings = LLMSettings.load()
    provider = settings.get_embedding_provider()
    if provider is None:
        msg = "No embedding provider configured"
        raise RuntimeError(msg)
    model = provider.provider.model
    base_url = provider.provider.base_url
    if not base_url:
        msg = "No embedding base_url configured"
        raise RuntimeError(msg)
    api_key = provider.provider.api_key or ""
    key_fp = hashlib.sha256(api_key.encode()).hexdigest()[:12]
    cache_key = f"{model}|{base_url}|{key_fp}"
    if cache_key not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(provider=provider)
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """清除embedding模型缓存."""
    _EMBEDDING_MODEL_CACHE.clear()


class EmbeddingModel:
    """文本嵌入模型封装，仅使用 OpenAI 兼容远程接口."""

    def __init__(self, provider: EmbeddingProviderConfig) -> None:
        """初始化嵌入模型."""
        self.provider = provider
        self._client: openai.AsyncOpenAI | None = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        """获取或延迟创建嵌入模型客户端."""
        if self._client is not None:
            return self._client
        self._client = self._create_client(self.provider)
        return self._client

    def _create_client(
        self,
        provider: EmbeddingProviderConfig,
    ) -> openai.AsyncOpenAI:
        """创建嵌入模型客户端."""
        base_url = provider.provider.base_url
        if not base_url:
            msg = "Embedding provider must have a base_url configured"
            raise RuntimeError(msg)
        return openai.AsyncOpenAI(
            api_key=provider.provider.api_key or "not-needed",
            base_url=base_url,
            timeout=_CLIENT_TIMEOUT,
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

    async def _async_batch_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """使用openai异步接口批量编码文本."""
        resp = await client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]

    async def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        return await self._async_encode_with_openai(
            self.client,
            self.provider.provider.model,
            text,
        )

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本为向量."""
        if not texts:
            return []
        return await self._async_batch_encode_with_openai(
            self.client,
            self.provider.provider.model,
            texts,
        )


def reset_embedding_singleton() -> None:
    """清除缓存并重置为初始状态（供测试使用）."""
    _EMBEDDING_MODEL_CACHE.clear()
