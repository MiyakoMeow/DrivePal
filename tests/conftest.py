"""共享测试配置和 fixtures."""

import os
from typing import TYPE_CHECKING

import pytest
import requests

from app.models.embedding import (
    EmbeddingModel,
    get_cached_embedding_model,
    reset_embedding_singleton,
)
from app.models.settings import EmbeddingProviderConfig, LLMProviderConfig, LLMSettings

if TYPE_CHECKING:
    from collections.abc import Generator

# PLR2004: HTTP 状态码
HTTP_OK = 200


def pytest_configure(config: pytest.Config) -> None:
    """注册自定义标记."""
    config.addinivalue_line("markers", "integration: 集成测试，需要真实的 LLM provider")


def pytest_addoption(parser: pytest.Parser) -> None:
    """添加自定义命令行选项."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行集成测试（需要真实 LLM provider）",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """默认跳过 integration 测试，除非显式启用."""
    run_integration = (
        config.getoption("--run-integration", default=False)
        or os.environ.get("INTEGRATION_TESTS") == "1"
    )
    if run_integration:
        return
    skip_integration = pytest.mark.skip(
        reason="需要 --run-integration 标志或 INTEGRATION_TESTS=1 环境变量",
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def _check_provider_reachable(provider: LLMProviderConfig) -> bool:
    """检查 provider 是否可达（发起真实 HTTP 请求）."""
    if not provider.provider.base_url:
        return True
    try:
        base = provider.provider.base_url.rstrip("/")
        resp = requests.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {provider.provider.api_key}"}
            if provider.provider.api_key
            else {},
            timeout=5,
        )
    except requests.RequestException:
        return False
    return resp.status_code == HTTP_OK


def get_available_provider() -> LLMProviderConfig | None:
    """获取第一个可达的 LLM provider，或 None."""
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        return None

    try:
        providers = settings.get_model_group_providers("default")
    except KeyError, ValueError, RuntimeError:
        return None

    fallback_provider: LLMProviderConfig | None = None
    for provider in providers:
        if not provider.provider.base_url:
            fallback_provider = fallback_provider or provider
            continue
        if _check_provider_reachable(provider):
            return provider
    return fallback_provider


@pytest.fixture
def llm_provider() -> LLMProviderConfig | None:
    """返回可达的 LLM provider（若有），否则 None."""
    return get_available_provider()


@pytest.fixture
def required_llm_provider(llm_provider: LLMProviderConfig | None) -> LLMProviderConfig:
    """返回可用 provider；不可用时直接 skip."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    return llm_provider


def _check_embedding_reachable(provider: EmbeddingProviderConfig) -> bool:
    """检查 embedding provider 是否可达."""
    if not provider.provider.base_url:
        return False
    try:
        base = provider.provider.base_url.rstrip("/")
        resp = requests.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {provider.provider.api_key}"}
            if provider.provider.api_key
            else {},
            timeout=5,
        )
    except requests.RequestException:
        return False
    return resp.status_code == HTTP_OK


def get_available_embedding() -> EmbeddingModel | None:
    """获取可达的 embedding 模型，或 None."""
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        return None
    provider = settings.get_embedding_provider()
    if provider is None or not _check_embedding_reachable(provider):
        return None
    return get_cached_embedding_model()


@pytest.fixture(scope="session")
def embedding() -> Generator[EmbeddingModel]:
    """会话级 embedding 实例，不可用时跳过."""
    reset_embedding_singleton()
    model = get_available_embedding()
    if model is None:
        pytest.skip("No embedding provider available")
        yield  # unreachable, for type checker
    else:
        yield model
    reset_embedding_singleton()
