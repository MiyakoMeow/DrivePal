"""LLM对话模型封装，基于openai SDK，支持多provider自动fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

import openai

from app.models.protocol import ChatModelProtocol
from app.models.settings import LLMProviderConfig, LLMSettings

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam
    from collections.abc import AsyncIterator


class ChatModel(ChatModelProtocol):
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

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """异步生成回复."""
        messages = self._build_messages(prompt, system_prompt)
        errors = []
        for provider in self.providers:
            try:
                client = self._create_async_client(provider)
                response = await client.chat.completions.create(
                    model=provider.provider.model,
                    messages=messages,
                    temperature=self._get_temperature(provider),
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue
        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    async def generate_stream(  # ty: ignore[invalid-method-override]
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复."""
        messages = self._build_messages(prompt, system_prompt)

        errors = []
        for provider in self.providers:
            try:
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
        system_prompt: str | None = None,
    ) -> list[str]:
        """批量生成回复."""
        return [await self.generate(p, system_prompt) for p in prompts]

    def is_available(self) -> bool:
        """检查远程 LLM 是否可响应."""
        import requests

        for provider in self.providers:
            if not provider.provider.base_url:
                continue
            try:
                base = provider.provider.base_url.rstrip("/")
                if base.endswith("/v1"):
                    base = base[:-3]
                resp = requests.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {provider.provider.api_key}"}
                    if provider.provider.api_key
                    else {},
                    timeout=5,
                )
                if resp.status_code == 200:
                    return True
            except Exception:
                continue
        return False
