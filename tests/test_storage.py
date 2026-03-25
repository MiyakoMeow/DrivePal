import pytest
import tempfile
from app.storage.json_store import JSONStore


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_json_store_read_write(temp_dir):
    store = JSONStore(temp_dir, "test.json")

    data = {"key": "value", "list": [1, 2, 3]}
    store.write(data)

    result = store.read()
    assert result == data


def test_json_store_append(temp_dir):
    store = JSONStore(temp_dir, "test.json", default_factory=list)

    store.append({"id": 1})
    store.append({"id": 2})

    result = store.read()
    assert len(result) == 2


def test_json_store_default_factory(temp_dir):
    store = JSONStore(temp_dir, "empty.json", default_factory=dict)
    result = store.read()
    assert result == {}
