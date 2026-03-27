"""模型配置，支持 qwen、DeepSeek 和其他 OpenAI 兼容接口."""

import os

_DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"


class ModelConfig:

    """模型配置."""

    PROVIDERS = {
        "qwen": {
            "base_url": os.getenv("VLLM_BASE_URL", _DEFAULT_VLLM_BASE_URL),
            "model": "Qwen/Qwen3.5-2B",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
        "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4"},
        "anthropic": {
            "base_url": "https://api.anthropic.com",
            "model": "claude-3-sonnet-20240229",
        },
    }

    @classmethod
    def get_provider(cls, name: str = "qwen"):
        """获取指定提供商的配置，默认返回qwen配置."""
        return cls.PROVIDERS.get(name, cls.PROVIDERS["qwen"])
