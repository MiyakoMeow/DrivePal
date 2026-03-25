"""模型配置，支持DeepSeek和其他OpenAI兼容接口"""


class ModelConfig:
    """模型配置"""

    PROVIDERS = {
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
    def get_provider(cls, name: str = "deepseek"):
        return cls.PROVIDERS.get(name, cls.PROVIDERS["deepseek"])
