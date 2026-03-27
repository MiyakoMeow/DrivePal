"""LLM对话模型封装，基于LangChain OpenAI兼容接口."""

from typing import Optional
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.utils import SecretStr

_DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"


class ChatModel:

    """LLM对话模型封装."""

    def __init__(
        self,
        model: str = "Qwen/Qwen3.5-2B",
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: str = os.getenv("VLLM_BASE_URL", _DEFAULT_VLLM_BASE_URL),
    ):
        """初始化对话模型."""
        self.model_name = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url
        self._client = None

    @property
    def client(self) -> ChatOpenAI:
        """获取或延迟创建LangChain ChatOpenAI客户端."""
        if self._client is None:
            api_key_str = self.api_key or ""
            self._client = ChatOpenAI(
                model_name=self.model_name,
                temperature=self.temperature,
                openai_api_key=SecretStr(api_key_str) if api_key_str else None,
                openai_api_base=self.base_url,
            )
        return self._client

    def generate(
        self, prompt: str, system_prompt: Optional[str] = None, **kwargs
    ) -> str:
        """生成回复."""
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
        """批量生成."""
        return [self.generate(p, system_prompt) for p in prompts]
