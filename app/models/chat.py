"""LLM对话模型封装，基于openai SDK，支持多provider自动fallback."""

import asyncio
import logging
from functools import cache
from typing import TYPE_CHECKING, Any, cast

import openai

from app.models._http import CLIENT_TIMEOUT as _CLIENT_TIMEOUT
from app.models.settings import (
    LLMProviderConfig,
    LLMSettings,
    NoDefaultModelGroupError,
    NoJudgeModelConfiguredError,
)
from app.models.types import ProviderConfig

logger = logging.getLogger(__name__)

_semaphore_cache: dict[str, tuple[asyncio.Semaphore, int]] = {}


def clear_semaphore_cache() -> None:
    """清理 provider semaphore 缓存和锁缓存（供测试使用）。"""
    _semaphore_cache.clear()
    _get_lock.cache_clear()


class ChatError(RuntimeError):
    """Chat模型错误基类."""

    def __init__(self, message: str) -> None:
        """初始化错误."""
        super().__init__(message)


class NoProviderError(ChatError):
    """没有可用provider错误."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("No LLM providers configured")


class AllProviderFailedError(ChatError):
    """所有provider都失败错误."""

    def __init__(self, details: str = "") -> None:
        """初始化错误."""
        msg = "All LLM providers failed"
        if details:
            msg += f": {details}"
        super().__init__(msg)


@cache
def _get_lock() -> asyncio.Lock:
    """获取或创建全局 asyncio.Lock."""
    return asyncio.Lock()


async def _get_provider_semaphore(
    provider_name: str,
    concurrency: int,
    model: str = "",
) -> asyncio.Semaphore:
    """获取或创建 provider 级别的 semaphore。"""
    async with _get_lock():
        if provider_name not in _semaphore_cache:
            _semaphore_cache[provider_name] = (
                asyncio.Semaphore(concurrency),
                concurrency,
            )
        else:
            _, existing_conc = _semaphore_cache[provider_name]
            if existing_conc != concurrency:
                logger.warning(
                    "Semaphore %r (model=%s) exists with concurrency=%d, "
                    "ignoring requested concurrency=%d",
                    provider_name,
                    model,
                    existing_conc,
                    concurrency,
                )
        return _semaphore_cache[provider_name][0]


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from openai.types.chat import ChatCompletionMessageParam


class ChatModel:
    """LLM对话模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[LLMProviderConfig] | None = None,
        temperature: float | None = None,
    ) -> None:
        """初始化对话模型，按provider顺序自动fallback."""
        if providers is None:
            settings = LLMSettings.load()
            providers = settings.llm_providers
        if not providers:
            raise NoProviderError
        self.providers = providers
        self.temperature = temperature

    def _create_client(
        self,
        provider: LLMProviderConfig,
    ) -> openai.AsyncOpenAI:
        """创建openai异步客户端."""
        kwargs: dict = {
            "api_key": provider.provider.api_key or "not-needed",
            "timeout": _CLIENT_TIMEOUT,
        }
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.AsyncOpenAI(**kwargs)

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> list[ChatCompletionMessageParam]:
        """构建消息列表."""
        messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _get_temperature(self, provider: LLMProviderConfig) -> float:
        """获取温度参数."""
        return (
            self.temperature if self.temperature is not None else provider.temperature
        )

    async def _acquire_slot(self, provider: LLMProviderConfig) -> asyncio.Semaphore:
        """获取 provider 的 semaphore slot."""
        provider_key = provider.provider.base_url or "default"
        return await _get_provider_semaphore(
            provider_key,
            provider.concurrency,
            model=provider.provider.model,
        )

    async def generate(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[ChatCompletionMessageParam] | None = None,
        **kwargs: object,
    ) -> str:
        """异步生成回复。kwargs 中支持 json_mode=True 以使用 JSON mode。"""
        if messages is None:
            messages = self._build_messages(prompt, system_prompt)
        json_mode = kwargs.pop("json_mode", False)
        errors = []
        for provider in self.providers:
            sem = await self._acquire_slot(provider)
            try:
                async with sem, self._create_client(provider) as client:
                    create_kwargs: dict = {
                        "model": provider.provider.model,
                        "messages": messages,
                        "temperature": self._get_temperature(provider),
                    }
                    if json_mode:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    response = await client.chat.completions.create(**create_kwargs)
                    return response.choices[0].message.content or ""
            except (openai.APIError, OSError, ValueError, TypeError, RuntimeError) as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue
        raise AllProviderFailedError("; ".join(errors))

    async def generate_stream(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[ChatCompletionMessageParam] | None = None,
        *,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """流式生成回复，指定 json_mode=True 以使用 JSON mode。"""
        if messages is None:
            messages = self._build_messages(prompt, system_prompt)

        errors = []
        for provider in self.providers:
            sem = await self._acquire_slot(provider)
            try:
                async with sem, self._create_client(provider) as client:
                    create_kwargs: dict = {
                        "model": provider.provider.model,
                        "messages": messages,
                        "temperature": self._get_temperature(provider),
                    }
                    if json_mode:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    stream = await client.chat.completions.create(
                        **create_kwargs,
                        stream=True,
                    )
                    async for chunk in stream:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yield delta.content
                    return
            except (openai.APIError, OSError, ValueError, TypeError, RuntimeError) as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise AllProviderFailedError("; ".join(errors))

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
        max_concurrency: int = 8,
        **kwargs: object,
    ) -> list[str]:
        """并行批量生成回复，通过 semaphore 限制并发保护 provider。"""
        if max_concurrency <= 0:
            msg = f"max_concurrency must be > 0, got {max_concurrency}"
            raise ValueError(msg)
        if not prompts:
            return []
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(p: str) -> str:
            async with sem:
                return await self.generate(
                    p, system_prompt, **cast("dict[str, Any]", kwargs)
                )

        return list(await asyncio.gather(*[_bounded(p) for p in prompts]))


def get_chat_model(temperature: float | None = None) -> ChatModel:
    """从配置创建 ChatModel 实例（使用缓存避免重复加载）."""
    settings = LLMSettings.load()
    if "default" not in settings.model_groups:
        raise NoDefaultModelGroupError
    providers = settings.get_model_group_providers("default")
    return ChatModel(providers=providers, temperature=temperature)


def get_judge_model() -> ChatModel:
    """从配置创建 judge ChatModel 实例（使用缓存避免重复加载）."""
    settings = LLMSettings.load()
    if settings.judge_provider is None:
        raise NoJudgeModelConfiguredError
    provider = LLMProviderConfig(
        provider=ProviderConfig(
            model=settings.judge_provider.provider.model,
            base_url=settings.judge_provider.provider.base_url,
            api_key=settings.judge_provider.provider.api_key,
        ),
        temperature=settings.judge_provider.temperature,
    )
    return ChatModel(providers=[provider])
