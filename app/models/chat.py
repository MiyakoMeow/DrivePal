"""LLM对话模型封装，基于LangChain OpenAI兼容接口，支持多provider自动fallback."""

from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.utils import SecretStr

from app.models.settings import LLMProviderConfig, LLMSettings


class ChatModel:
    """LLM对话模型封装，支持多provider自动fallback."""

    def __init__(
        self,
        providers: list[LLMProviderConfig] | None = None,
        temperature: float | None = None,
    ):
        if providers is None:
            settings = LLMSettings.load()
            providers = settings.llm_providers
        if not providers:
            raise RuntimeError("No LLM providers configured")
        self.providers = providers
        self.temperature = temperature

    def _create_client(self, provider: LLMProviderConfig) -> ChatOpenAI:
        temp = (
            self.temperature if self.temperature is not None else provider.temperature
        )
        kwargs: dict = {
            "model": provider.model,
            "temperature": temp,
        }
        if provider.api_key:
            kwargs["openai_api_key"] = SecretStr(provider.api_key)
        else:
            kwargs["openai_api_key"] = None
        if provider.base_url:
            kwargs["openai_api_base"] = provider.base_url
        return ChatOpenAI(**kwargs)

    def _invoke_provider(
        self, provider: LLMProviderConfig, messages: list, **kwargs
    ) -> str:
        client = self._create_client(provider)
        response = client.invoke(messages, **kwargs)
        return str(response.content)

    def generate(
        self, prompt: str, system_prompt: Optional[str] = None, **kwargs
    ) -> str:
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        errors = []
        for provider in self.providers:
            try:
                return self._invoke_provider(provider, messages, **kwargs)
            except Exception as e:
                errors.append(f"{provider.model}: {e}")
                continue

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    def batch_generate(
        self, prompts: list[str], system_prompt: Optional[str] = None
    ) -> list[str]:
        return [self.generate(p, system_prompt) for p in prompts]
