"""文本嵌入模型封装，支持 HuggingFace 本地模型和 OpenAI 兼容远程接口."""

from typing import TYPE_CHECKING

import openai

from app.models.settings import EmbeddingProviderConfig, LLMSettings, ProviderConfig

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_EMBEDDING_MODEL_CACHE: dict[str, EmbeddingModel] = {}


def _auto_detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def get_cached_embedding_model() -> EmbeddingModel:
    """获取缓存的embedding模型实例，避免重复加载."""
    settings = LLMSettings.load()
    provider = settings.get_embedding_provider()
    model = provider.provider.model if provider else "BAAI/bge-small-zh-v1.5"
    base_url = provider.provider.base_url if provider else ""
    device = provider.device if provider else ""
    device = device or ""
    cache_key = f"{model}|{base_url}|{device}"
    if cache_key not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(provider=provider)
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """清除embedding模型缓存."""
    _EMBEDDING_MODEL_CACHE.clear()


class EmbeddingModel:
    """文本嵌入模型封装，支持单provider."""

    def __init__(
        self,
        provider: EmbeddingProviderConfig | None = None,
    ) -> None:
        """初始化嵌入模型."""
        if provider is None:
            try:
                settings = LLMSettings.load()
                provider = settings.get_embedding_provider()
            except RuntimeError:
                pass
        if provider is None:
            provider = EmbeddingProviderConfig(
                provider=ProviderConfig(model="BAAI/bge-small-zh-v1.5"),
                device=_auto_detect_device(),
            )
        self.provider = provider
        self._client: openai.AsyncOpenAI | SentenceTransformer | None = None

    @property
    def client(self) -> openai.AsyncOpenAI | SentenceTransformer:
        """获取或延迟创建嵌入模型客户端."""
        if self._client is not None:
            return self._client
        self._client = self._create_client(self.provider)
        return self._client

    def _create_client(
        self,
        provider: EmbeddingProviderConfig,
    ) -> openai.AsyncOpenAI | SentenceTransformer:
        """创建嵌入模型客户端."""
        device = provider.device or _auto_detect_device()
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

    async def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        cl = self.client
        if isinstance(cl, openai.AsyncOpenAI):
            return await self._async_encode_with_openai(
                cl,
                self.provider.provider.model,
                text,
            )
        return self._encode_with_local(cl, text)

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本为向量."""
        cl = self.client
        if isinstance(cl, openai.AsyncOpenAI):
            return await self._async_batch_encode_with_openai(
                cl,
                self.provider.provider.model,
                texts,
            )
        return self._batch_encode_with_local(cl, texts)


def reset_embedding_singleton() -> None:
    """清除缓存并重置为初始状态（供测试使用）."""
    _EMBEDDING_MODEL_CACHE.clear()
