"""共享测试配置和 fixtures."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.models.embedding import (
    EmbeddingModel,
    get_cached_embedding_model,
    reset_embedding_singleton,
)
from app.models.settings import LLMProviderConfig, LLMSettings
from tests.fixtures import (
    MODULES_WITH_DATA_DIR,
    MODULES_WITH_DATA_ROOT,
    reset_all_singletons,
)

if TYPE_CHECKING:
    from collections.abc import Generator


def pytest_configure(config: pytest.Config) -> None:
    """注册自定义标记."""
    config.addinivalue_line("markers", "integration: 集成测试，需要真实的 LLM provider")
    config.addinivalue_line("markers", "llm: 需要 LLM provider 的测试")
    config.addinivalue_line("markers", "embedding: 需要 embedding provider 的测试")


def pytest_addoption(parser: pytest.Parser) -> None:
    """添加自定义命令行选项."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行集成测试（需要真实 LLM provider）",
    )
    parser.addoption(
        "--test-llm",
        action="store_true",
        default=False,
        help="运行需要 LLM provider 的测试",
    )
    parser.addoption(
        "--test-embedding",
        action="store_true",
        default=False,
        help="运行需要 embedding provider 的测试",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """根据命令行选项跳过相应测试."""
    run_integration = config.getoption("--run-integration", default=False)
    test_llm = config.getoption("--test-llm", default=False)
    test_embedding = config.getoption("--test-embedding", default=False)

    for item in items:
        if "integration" in item.keywords and not run_integration:
            item.add_marker(pytest.mark.skip(reason="需要 --run-integration 标志"))
        if "llm" in item.keywords and not test_llm:
            item.add_marker(pytest.mark.skip(reason="需要 --test-llm 标志"))
        if "embedding" in item.keywords and not test_embedding:
            item.add_marker(pytest.mark.skip(reason="需要 --test-embedding 标志"))


@pytest.fixture(scope="session")
def llm_provider() -> LLMProviderConfig:
    """返回 LLM provider，由 --test-llm 标记控制是否启用.

    跳过逻辑由 pytest_collection_modifyitems 中的 marker 处理，
    此处仅验证配置可用性。
    """
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        pytest.skip("无法加载 LLM 配置")
    try:
        providers = settings.get_model_group_providers("default")
    except KeyError, ValueError, RuntimeError:  # PEP-758: comma-separated except
        pytest.skip("无法获取 LLM providers")
    if not providers:
        pytest.skip("没有配置 LLM providers")
    return providers[0]


@pytest.fixture(scope="session")
def embedding() -> Generator[EmbeddingModel]:
    """会话级 embedding 实例，由 --test-embedding 标记控制是否启用.

    跳过逻辑由 pytest_collection_modifyitems 中的 marker 处理，
    此处仅验证配置可用性。
    """
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        pytest.skip("无法加载 embedding 配置")
    # 验证 embedding provider 配置存在（模型由全局单例创建）
    try:
        provider = settings.get_embedding_provider()
    except KeyError, RuntimeError:  # PEP-758: comma-separated except
        pytest.skip("无法获取 embedding provider")
    if provider is None:
        pytest.skip("没有配置 embedding provider")
    reset_embedding_singleton()
    try:
        model = get_cached_embedding_model()
        yield model
    finally:
        reset_embedding_singleton()


@pytest.fixture
def app_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient]:
    """提供 TestClient 实例，隔离数据目录."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    target = Path(data_dir)
    with ExitStack() as stack:
        for mod in MODULES_WITH_DATA_DIR:
            stack.enter_context(patch(f"{mod}.DATA_DIR", target))
        for mod in MODULES_WITH_DATA_ROOT:
            stack.enter_context(patch(f"{mod}.DATA_ROOT", target))
        reset_all_singletons()
        with TestClient(app) as c:
            yield c
        reset_all_singletons()
