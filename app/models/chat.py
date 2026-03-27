import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


class ChatModel:
    def __init__(
        self,
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
    ):
        self.model_name = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key not provided and DEEPSEEK_API_KEY environment variable not set"
            )
        self.base_url = base_url
        self._client = None

    @property
    def client(self) -> ChatOpenAI:
        if self._client is None:
            self._client = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=self.temperature,
            )
        return self._client

    def generate(
        self, prompt: str, system_prompt: Optional[str] = None, **kwargs
    ) -> str:
        """生成回复"""
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        try:
            response = self.client.invoke(messages, **kwargs)
            return str(response.content)
        except Exception as e:
            error_type = type(e).__name__.lower()
            if "token" in error_type or "auth" in error_type:
                raise RuntimeError("Invalid API key") from None
            raise RuntimeError(f"LLM API call failed: {type(e).__name__}") from e

    def batch_generate(
        self, prompts: list[str], system_prompt: Optional[str] = None
    ) -> list[str]:
        """批量生成"""
        return [self.generate(p, system_prompt) for p in prompts]
