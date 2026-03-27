import pytest
import tempfile
from app.memory.memory import MemoryModule


@pytest.fixture
def temp_data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_memory_module_init(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    assert memory.data_dir == temp_data_dir


def test_write_event(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    event = {"content": "测试事件", "type": "meeting"}
    event_id = memory.write(event)
    assert event_id is not None


def test_search_keyword(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    memory.write({"content": "下午3点会议", "type": "meeting"})

    results = memory.search("会议", mode="keyword")
    assert len(results) > 0


def test_search_llm_only(temp_data_dir):
    memory = MemoryModule(temp_data_dir)
    results = memory.search("会议", mode="llm_only")
    assert results == []  # 无记忆模式返回空


def test_search_by_llm_returns_list():
    memory = MemoryModule(data_dir="data/test", embedding_model=None)
    result = memory._search_by_llm("明天有什么日程")
    assert isinstance(result, list)


def test_search_keyword_includes_description(temp_data_dir):
    """Test that keyword search includes description field."""
    memory = MemoryModule(temp_data_dir, chat_model=None)
    memory.write(
        {"content": "regular meeting", "description": "afternoon sync", "event_id": "1"}
    )

    results = memory.search("afternoon", mode="keyword")
    assert len(results) > 0, "keyword search should find 'afternoon' in description"


def test_get_history_negative_limit(temp_data_dir):
    """Test that negative limit raises ValueError."""
    memory = MemoryModule(temp_data_dir)
    memory.write({"content": "test1"})

    with pytest.raises(ValueError, match="limit must be non-negative"):
        memory.get_history(limit=-1)


def test_cosine_similarity_numpy(temp_data_dir):
    """Test that cosine similarity handles numpy arrays."""
    import numpy as np

    memory = MemoryModule(temp_data_dir)

    vec1 = np.array([0.1, 0.2, 0.3])
    vec2 = np.array([0.1, 0.2, 0.3])

    result = memory._cosine_similarity(vec1, vec2)
    assert abs(result - 1.0) < 0.001, "identical vectors should have similarity ~1"
