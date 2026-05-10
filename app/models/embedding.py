"""文本嵌入模型封装，仅支持 OpenAI 兼容远程接口."""

import asyncio
import contextlib
import hashlib
import logging
import random

import openai

from app.models._http import CLIENT_TIMEOUT as _CLIENT_TIMEOUT
from app.models.settings import EmbeddingProviderConfig, LLMSettings

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL_CACHE: dict[str, EmbeddingModel] = {}
_background_tasks: set[asyncio.Task[None]] = set()

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.0
_MAX_RETRY_DELAY_SECONDS = 10.0

_RETRYABLE_EXCEPTIONS = (
    OSError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


def _finalize_background_task(task: asyncio.Task[object]) -> None:
    """回收后台关闭 task 并消费异常，避免未检索异常告警。"""
    _background_tasks.discard(task)
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc is not None:
            logger.warning("Background cleanup task failed: %s", exc)


def get_cached_embedding_model(embedding_batch_size: int = 32) -> EmbeddingModel:
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
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(
            provider=provider, batch_size=embedding_batch_size
        )
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """关闭所有缓存的客户端并清除缓存。"""
    if not _EMBEDDING_MODEL_CACHE:
        return
    models = list(_EMBEDDING_MODEL_CACHE.values())
    _EMBEDDING_MODEL_CACHE.clear()
    for model in models:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中循环，用 asyncio.run 同步关闭
            asyncio.run(model.aclose())
        else:
            # 有运行中循环，创建 task 后台关闭，task 引用入 set 防 GC
            task = loop.create_task(model.aclose())
            _background_tasks.add(task)
            task.add_done_callback(_finalize_background_task)


class EmbeddingModel:
    """文本嵌入模型封装，仅使用 OpenAI 兼容远程接口."""

    def __init__(self, provider: EmbeddingProviderConfig, batch_size: int = 32) -> None:
        """初始化嵌入模型."""
        self.provider = provider
        self._client: openai.AsyncOpenAI | None = None
        self.batch_size = batch_size

    @property
    def client(self) -> openai.AsyncOpenAI:
        """获取或延迟创建嵌入模型客户端."""
        if self._client is not None:
            return self._client
        self._client = self._create_client(self.provider)
        return self._client

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端，释放连接池资源."""
        if self._client is not None:
            with contextlib.suppress(RuntimeError):
                await self._client.close()
            self._client = None

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

    async def _encode_batch_with_retry(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        batch: list[str],
        start: int,
        total: int,
    ) -> list[list[float]]:
        """对单批文本进行编码，含重试逻辑."""
        last_error: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = await client.embeddings.create(model=model, input=batch)
            except _RETRYABLE_EXCEPTIONS as e:
                last_error = e
                logger.warning(
                    "Embedding batch %d-%d failed (attempt %d/%d): %s",
                    start,
                    min(start + self.batch_size, total),
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                    e,
                )
            else:
                if not resp.data:
                    msg = "No embedding data received"
                    last_error = ValueError(msg)
                    logger.warning(
                        "Embedding batch %d-%d returned empty data (attempt %d/%d)",
                        start,
                        min(start + self.batch_size, total),
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                    )
                else:
                    return [
                        d.embedding for d in sorted(resp.data, key=lambda x: x.index)
                    ]
            if attempt < _RETRY_ATTEMPTS - 1:
                delay = min(
                    _RETRY_BASE_DELAY_SECONDS * (2**attempt),
                    _MAX_RETRY_DELAY_SECONDS,
                ) * random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)
        if last_error is not None:
            raise last_error
        msg = "Embedding batch encode failed after all retries"
        raise RuntimeError(msg)

    async def _async_batch_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """使用openai异步接口批量编码文本（含分批与重试）."""
        all_vectors: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self.batch_size):
            batch = texts[start : start + self.batch_size]
            batch_vectors = await self._encode_batch_with_retry(
                client, model, batch, start, total
            )
            all_vectors.extend(batch_vectors)
        return all_vectors

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
    """关闭所有客户端、清除缓存并重置为初始状态（供测试使用）."""
    clear_embedding_model_cache()
