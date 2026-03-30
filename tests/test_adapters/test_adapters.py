"""记忆适配器测试."""

from pathlib import Path

from adapters.memory_adapters import ADAPTERS
from adapters.memory_adapters.keyword_adapter import KeywordAdapter


SAMPLE_HISTORY = "[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3\n[2025-03-05 07:45] Gary Allen: Set navigation volume to high\n"


def test_adapters_registry_has_all_four() -> None:
    """测试 ADAPTERS 注册表包含所有四种适配器类型."""
    assert set(ADAPTERS.keys()) == {"keyword", "llm_only", "embeddings", "memory_bank"}


def test_all_adapters_have_tag() -> None:
    """测试所有适配器都有 TAG 属性."""
    for name, cls in ADAPTERS.items():
        adapter = cls.__new__(cls)
        assert hasattr(adapter, "TAG")
        assert adapter.TAG == name or adapter.TAG == name.replace("_", "")


def test_keyword_adapter_add_and_search(tmp_path: Path) -> None:
    """测试 KeywordAdapter 可以添加历史记录和搜索."""
    adapter = KeywordAdapter(data_dir=str(tmp_path / "keyword"))
    store = adapter.add(SAMPLE_HISTORY)
    assert store is not None
    client = adapter.get_search_client(store)
    results = client.search(query="seat heating", top_k=5)
    assert isinstance(results, list)


def test_all_adapters_have_required_methods() -> None:
    """测试所有适配器都有必需的方法."""
    for name, cls in ADAPTERS.items():
        adapter = cls.__new__(cls)
        assert callable(getattr(adapter, "add", None))
        assert callable(getattr(adapter, "get_search_client", None))
