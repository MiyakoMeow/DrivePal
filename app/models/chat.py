"""LLM对话模型封装，基于openai SDK，支持多provider自动fallback."""

import asyncio
import contextlib
import hashlib
from functools import cache
from typing import TYPE_CHECKING, Any

import openai

from app.models._http import CLIENT_TIMEOUT as _CLIENT_TIMEOUT
from app.models.exceptions import ModelGroupNotFoundError
from app.models.settings import (
    LLMProviderConfig,
    LLMSettings,
    NoDefaultModelGroupError,
    NoJudgeModelConfiguredError,
)

_semaphore_cache: dict[str, asyncio.Semaphore] = {}
_client_cache: dict[tuple[str, str], openai.AsyncOpenAI] = {}


@cache
def _get_client_cache_lock() -> asyncio.Lock:
    """获取或创建客户端缓存锁."""
    return asyncio.Lock()


def _make_client(provider: LLMProviderConfig) -> openai.AsyncOpenAI:
    """创建 openai 异步客户端（模块级工厂函数）。"""
    kwargs: dict = {
        "api_key": provider.provider.api_key or "not-needed",
        "timeout": _CLIENT_TIMEOUT,
    }
    if provider.provider.base_url:
        kwargs["base_url"] = provider.provider.base_url
    return openai.AsyncOpenAI(**kwargs)


async def _get_cached_client(
    provider: LLMProviderConfig,
) -> openai.AsyncOpenAI:
    """获取或创建缓存的 AsyncOpenAI 客户端，按 (base_url, api_key) 去重。"""
    cache_key = (
        provider.provider.base_url or "",
        hashlib.sha256((provider.provider.api_key or "").encode()).hexdigest(),
    )
    async with _get_client_cache_lock():
        if cache_key not in _client_cache:
            _client_cache[cache_key] = _make_client(provider)
        return _client_cache[cache_key]


async def close_client_cache() -> None:
    """关闭所有缓存的客户端（lifespan 关闭时调用）。"""
    async with _get_client_cache_lock():
        clients = list(_client_cache.values())
        _client_cache.clear()
    for client in clients:
        with contextlib.suppress(Exception):
            await client.close()


def clear_semaphore_cache() -> None:
    """清理 provider semaphore 缓存和客户端缓存（供测试使用）。

    注意：此函数不关闭缓存的 AsyncOpenAI 客户端。
    测试应在 teardown 中使用 close_client_cache() 清理连接，
    然后调用此函数重置缓存状态。
    """
    _semaphore_cache.clear()
    _client_cache.clear()
    _get_lock.cache_clear()
    _get_client_cache_lock.cache_clear()


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
) -> asyncio.Semaphore:
    """获取或创建 provider 级别的 semaphore."""
    async with _get_lock():
        if provider_name not in _semaphore_cache:
            _semaphore_cache[provider_name] = asyncio.Semaphore(concurrency)
        return _semaphore_cache[provider_name]


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam


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
        # 最后一次调用的完整响应消息（含 reasoning_content 等 DeepSeek 扩展字段）
        self.last_message: ChatCompletionMessage | dict[str, Any] | None = None

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
        return await _get_provider_semaphore(provider_key, provider.concurrency)

    @staticmethod
    def _accumulate_stream_delta(
        delta: object,
        *,
        reasoning_parts: list[str],
        content_parts: list[str],
        tool_calls_acc: dict[int, dict],
    ) -> None:
        """累积流式块中的 reasoning_content、content、tool_calls 到各累加器。"""
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            reasoning_parts.append(reasoning)
        content = getattr(delta, "content", None)
        if content:
            content_parts.append(content)
        tool_calls = getattr(delta, "tool_calls", None)
        if not tool_calls:
            return
        for tc in tool_calls:
            idx = tc.index
            if idx in tool_calls_acc:
                if tc.function and tc.function.arguments:
                    tool_calls_acc[idx]["function"]["arguments"] += (
                        tc.function.arguments
                    )
            else:
                tool_calls_acc[idx] = {
                    "id": tc.id or "",
                    "type": tc.type or "function",
                    "function": {
                        "name": tc.function.name if tc.function else "",
                        "arguments": tc.function.arguments if tc.function else "",
                    },
                }

    async def generate(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[ChatCompletionMessageParam] | None = None,
        **kwargs: object,
    ) -> str:
        """异步生成回复。kwargs 中支持 json_mode=True 以使用 JSON mode。

        响应详情（含 reasoning_content、tool_calls）通过 self.last_message 访问（仅最后一次调用有效）。
        """
        if messages is None:
            messages = self._build_messages(prompt, system_prompt)
        json_mode = kwargs.pop("json_mode", False)
        errors = []
        for provider in self.providers:
            sem = await self._acquire_slot(provider)
            try:
                async with sem:
                    client = await _get_cached_client(provider)
                    create_kwargs: dict = {
                        "model": provider.provider.model,
                        "messages": messages,
                        "temperature": self._get_temperature(provider),
                    }
                    if json_mode:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    # 透传剩余 kwargs（extra_body, reasoning_effort, max_tokens 等）
                    create_kwargs.update(kwargs)
                    response = await client.chat.completions.create(**create_kwargs)
                    self.last_message = response.choices[0].message
                    return self.last_message.content or ""
            except (openai.APIError, OSError, ValueError, TypeError, RuntimeError) as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue
        raise AllProviderFailedError("; ".join(errors))

    async def generate_stream(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[ChatCompletionMessageParam] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复。kwargs 中支持 json_mode=True 以使用 JSON mode。

        支持 DeepSeek 思考模式（reasoning_content 存于 self.last_message）和工具调用分块累积.
        """
        if messages is None:
            messages = self._build_messages(prompt, system_prompt)
        json_mode = kwargs.pop("json_mode", False)

        errors = []
        for provider in self.providers:
            sem = await self._acquire_slot(provider)
            try:
                async with sem:
                    client = await _get_cached_client(provider)
                    create_kwargs: dict = {
                        "model": provider.provider.model,
                        "messages": messages,
                        "temperature": self._get_temperature(provider),
                        "stream": True,
                    }
                    if json_mode:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    create_kwargs.update(kwargs)
                    stream = await client.chat.completions.create(**create_kwargs)
                    reasoning_parts: list[str] = []
                    content_parts: list[str] = []
                    tool_calls_acc: dict[int, dict] = {}
                    async for chunk in stream:
                        delta = chunk.choices[0].delta
                        self._accumulate_stream_delta(
                            delta,
                            reasoning_parts=reasoning_parts,
                            content_parts=content_parts,
                            tool_calls_acc=tool_calls_acc,
                        )
                        if delta.content:
                            yield delta.content
                    # 流结束后构建 last_message（含 reasoning_content + tool_calls 供多轮拼接）
                    full_reasoning = (
                        "".join(reasoning_parts) if reasoning_parts else None
                    )
                    msg: dict = {"role": "assistant", "content": "".join(content_parts)}
                    if full_reasoning:
                        msg["reasoning_content"] = full_reasoning
                    if tool_calls_acc:
                        msg["tool_calls"] = [
                            tool_calls_acc[i] for i in sorted(tool_calls_acc)
                        ]
                    self.last_message = msg
                    return
            except (openai.APIError, OSError, ValueError, TypeError, RuntimeError) as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue

        raise AllProviderFailedError("; ".join(errors))

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
    ) -> list[str]:
        """并行批量生成，使用首个 provider 的 semaphore 控制并发。"""
        if not prompts:
            return []
        sem = await self._acquire_slot(self.providers[0])

        async def _bounded(p: str) -> str:
            async with sem:
                return await self.generate(p, system_prompt)

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
    try:
        providers = settings.get_model_group_providers(settings.judge_model_group)
    except ModelGroupNotFoundError:
        raise NoJudgeModelConfiguredError from None
    if not providers:
        raise NoJudgeModelConfiguredError
    return ChatModel(providers=providers)
