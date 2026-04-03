"""LLM对话模型封装，基于openai SDK，支持多provider自动fallback."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING, TypeVar

import openai

import asyncio

from app.models.settings import LLMProviderConfig, LLMSettings

_provider_semaphore_cache: dict[str, asyncio.Semaphore] = {}
_provider_semaphore_lock: asyncio.Lock | None = None


async def _get_provider_semaphore(
    provider_name: str, concurrency: int
) -> asyncio.Semaphore:
    """获取或创建 provider 级别的 semaphore."""
    global _provider_semaphore_lock
    if _provider_semaphore_lock is None:
        _provider_semaphore_lock = asyncio.Lock()

    async with _provider_semaphore_lock:
        if provider_name not in _provider_semaphore_cache:
            _provider_semaphore_cache[provider_name] = asyncio.Semaphore(concurrency)
        return _provider_semaphore_cache[provider_name]


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
    from openai.types.chat import ChatCompletionMessageParam

_T = TypeVar("_T")


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
            raise RuntimeError("No LLM providers configured")
        self.providers = providers
        self.temperature = temperature

    def _create_client(self, provider: LLMProviderConfig) -> openai.OpenAI:
        """创建openai同步客户端."""
        kwargs: dict = {
            "api_key": provider.provider.api_key or "not-needed",
        }
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.OpenAI(**kwargs)

    def _create_async_client(
        self,
        provider: LLMProviderConfig,
    ) -> openai.AsyncOpenAI:
        """创建openai异步客户端."""
        kwargs: dict = {
            "api_key": provider.provider.api_key or "not-needed",
        }
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.AsyncOpenAI(**kwargs)

    def _build_messages(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
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
        return await _get_provider_semaphore(provider_key, provider.concurrency)

    async def _run_with_semaphore(
        self, provider: LLMProviderConfig, coro: Awaitable[_T]
    ) -> _T:
        """使用 provider semaphore 执行协程."""
        sem = await self._acquire_slot(provider)
        async with sem:
            return await coro

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **_kwargs: object,
    ) -> str:
        """异步生成回复."""
        messages = self._build_messages(prompt, system_prompt)
        errors = []
        for provider in self.providers:
            try:
                client = self._create_async_client(provider)
                coro = client.chat.completions.create(
                    model=provider.provider.model,
                    messages=messages,
                    temperature=self._get_temperature(provider),
                )
                response = await self._run_with_semaphore(provider, coro)
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue
        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **_kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复."""
        messages = self._build_messages(prompt, system_prompt)

        errors = []
        for provider in self.providers:
            sem = await self._acquire_slot(provider)
            try:
                async with sem:
                    client = self._create_async_client(provider)
                    stream = await client.chat.completions.create(
                        model=provider.provider.model,
                        messages=messages,
                        temperature=self._get_temperature(provider),
                        stream=True,
                    )
                    async for chunk in stream:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yield delta.content
                    return
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: Optional[str] | None = None,
    ) -> list[str]:
        """批量生成回复."""
        return [await self.generate(p, system_prompt) for p in prompts]
