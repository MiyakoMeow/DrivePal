"""测试 FaissIndex 封装性（get_metadata 返回副本）。"""

import pytest

from app.memory.stores.memory_bank.faiss_index import FaissIndex


@pytest.fixture
def faiss_index_with_data():
    """构造含数据的 FaissIndex 实例（绕过 __init__ 避免 faiss 依赖）。"""
    idx = FaissIndex.__new__(FaissIndex)
    idx._metadata = {"id1": {"content": "hello"}, "id2": {"content": "world"}}
    idx._extra = {"summary": "test"}
    idx._id_to_meta = {}
    return idx


def test_get_metadata_returns_copy(faiss_index_with_data):
    """get_metadata 返回副本，不可外部 mutate。"""
    meta = faiss_index_with_data.get_metadata()
    original_len = len(meta)
    meta["new_key"] = "injected"
    assert len(faiss_index_with_data.get_metadata()) == original_len
    assert "new_key" not in faiss_index_with_data.get_metadata()
