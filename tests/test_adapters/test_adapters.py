"""记忆适配器测试."""

from adapters.memory_adapters import ADAPTERS
from adapters.memory_adapters.keyword_adapter import KeywordAdapter


SAMPLE_HISTORY = "[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3\n[2025-03-05 07:45] Gary Allen: Set navigation volume to high\n"


def test_adapters_registry_has_all_four():
    """Test that ADAPTERS registry contains all four adapter types."""
    assert set(ADAPTERS.keys()) == {"keyword", "llm_only", "embeddings", "memory_bank"}


def test_all_adapters_have_tag():
    """Test that all adapters have a TAG attribute."""
    for name, cls in ADAPTERS.items():
        adapter = cls.__new__(cls)
        assert hasattr(adapter, "TAG")
        assert adapter.TAG == name or adapter.TAG == name.replace("_", "")


def test_keyword_adapter_add_and_search(tmp_path):
    """Test KeywordAdapter can add history and search."""
    adapter = KeywordAdapter(data_dir=str(tmp_path / "keyword"))
    store = adapter.add(SAMPLE_HISTORY)
    assert store is not None
    client = adapter.get_search_client(store)
    results = client.search(query="seat heating", top_k=5)
    assert isinstance(results, list)


def test_all_adapters_have_required_methods():
    """Test that all adapters have the required methods."""
    for name, cls in ADAPTERS.items():
        adapter = cls.__new__(cls)
        assert callable(getattr(adapter, "add", None))
        assert callable(getattr(adapter, "get_search_client", None))
        assert callable(getattr(adapter, "init_state", None))
        assert callable(getattr(adapter, "close_state", None))
