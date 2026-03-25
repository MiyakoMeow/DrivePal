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
    memory = MemoryModule(data_dir="~/tmp/test_memory", embedding_model=None)
    result = memory._search_by_llm("明天有什么日程")
    assert isinstance(result, list)
