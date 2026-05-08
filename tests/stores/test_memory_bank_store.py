"""MemoryBankStore 编排层测试。mock embedding + LLM + tmp_path。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import MemoryEvent


def _make_embedding(dim: int = 8) -> AsyncMock:
    rng = np.random.RandomState(42)
    model = AsyncMock()
    model.encode = AsyncMock(
        side_effect=lambda text: (
            rng.randn(dim) / np.linalg.norm(rng.randn(dim))
        ).tolist()
    )
    model.batch_encode = AsyncMock(
        side_effect=lambda texts: [
            (rng.randn(dim) / np.linalg.norm(rng.randn(dim))).tolist() for _ in texts
        ]
    )
    return model


def _make_chat_model(response: str = "summary text") -> AsyncMock:
    model = AsyncMock()
    model.generate = AsyncMock(return_value=response)
    return model


@pytest.fixture
def tmp_store(tmp_path: Path) -> MemoryBankStore:
    emb = _make_embedding()
    return MemoryBankStore(tmp_path, embedding_model=emb)


@pytest.fixture
def full_store(tmp_path: Path) -> MemoryBankStore:
    emb = _make_embedding()
    chat = _make_chat_model("summary result")
    return MemoryBankStore(tmp_path, embedding_model=emb, chat_model=chat)


# --- write_interaction ---


@pytest.mark.asyncio
async def test_write_interaction_returns_event_id(tmp_store: MemoryBankStore) -> None:
    result = await tmp_store.write_interaction("hello", "world")
    assert result.event_id
    assert isinstance(result.event_id, str)


@pytest.mark.asyncio
async def test_write_interaction_stores_metadata(
    tmp_store: MemoryBankStore,
) -> None:
    await tmp_store.write_interaction(
        "set seat to 45", "seat set", user_name="Gary", ai_name="Bot"
    )
    meta = tmp_store._index.get_metadata("default")
    assert len(meta) == 1
    assert "Gary" in meta[0]["speakers"]
    assert "Bot" in meta[0]["speakers"]


@pytest.mark.asyncio
async def test_write_interaction_no_embedding_raises(tmp_path: Path) -> None:
    store = MemoryBankStore(tmp_path)
    with pytest.raises(RuntimeError, match="embedding_client required"):
        await store.write_interaction("a", "b")


@pytest.mark.asyncio
async def test_write_interaction_with_user_id(tmp_path: Path) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    result = await store.write_interaction("hello", "world", user_id="alice")
    assert result.event_id
    meta_alice = store._index.get_metadata("alice")
    meta_default = store._index.get_metadata("default")
    assert len(meta_alice) == 1
    assert len(meta_default) == 0


# --- search ---


@pytest.mark.asyncio
async def test_search_after_write(tmp_store: MemoryBankStore) -> None:
    await tmp_store.write_interaction("set seat to 45", "seat set to 45")
    results = await tmp_store.search("seat", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_empty_index(tmp_store: MemoryBankStore) -> None:
    results = await tmp_store.search("anything")
    assert results == []


@pytest.mark.asyncio
async def test_search_user_isolation(tmp_path: Path) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store.write_interaction("alice topic", "response", user_id="alice")
    await store.write_interaction("bob topic", "response", user_id="bob")
    results = await store.search("alice topic", top_k=5, user_id="alice")
    assert len(results) >= 1
    results_bob = await store.search("alice topic", top_k=5, user_id="bob")
    for r in results_bob:
        assert "alice" not in r.event.get("source", "").lower()


@pytest.mark.asyncio
async def test_search_no_embedding_returns_empty(tmp_path: Path) -> None:
    store = MemoryBankStore(tmp_path)
    results = await store.search("test")
    assert results == []


@pytest.mark.asyncio
async def test_search_prepend_overall_context(tmp_path: Path) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store.write_interaction("hello", "world")
    ui = store._index._ensure_user("default")
    ui.extra["overall_summary"] = "user prefers cool temp"
    results = await store.search("hello", top_k=5)
    assert results[0].source == "overall"
    assert "cool temp" in results[0].event["content"]


@pytest.mark.asyncio
async def test_search_prepend_filters_empty(tmp_path: Path) -> None:
    from app.memory.memory_bank.summarizer import GENERATION_EMPTY

    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store.write_interaction("hello", "world")
    ui = store._index._ensure_user("default")
    ui.extra["overall_summary"] = GENERATION_EMPTY
    results = await store.search("hello", top_k=5)
    assert results[0].source != "overall" or "GENERATION_EMPTY" not in results[
        0
    ].event.get("content", "")


# --- write ---


@pytest.mark.asyncio
async def test_write_returns_id(tmp_store: MemoryBankStore) -> None:
    event = MemoryEvent(content="test event", type="reminder")
    eid = await tmp_store.write(event)
    assert eid
    assert isinstance(eid, str)


@pytest.mark.asyncio
async def test_write_multi_speaker_pairs(tmp_path: Path) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    content = "Gary: set seat to 45\nPatricia: set AC to 22"
    event = MemoryEvent(content=content, type="reminder")
    eid = await store.write(event)
    assert eid
    meta = store._index.get_metadata("default")
    assert len(meta) == 1
    assert meta[0]["speakers"] == ["Gary", "Patricia"]


@pytest.mark.asyncio
async def test_write_single_speaker_fallback(
    tmp_store: MemoryBankStore,
) -> None:
    event = MemoryEvent(content="plain text", type="reminder")
    eid = await tmp_store.write(event)
    assert eid
    meta = tmp_store._index.get_metadata("default")
    assert len(meta) == 1
    assert "System" in meta[0]["speakers"]


@pytest.mark.asyncio
async def test_write_no_embedding_raises(tmp_path: Path) -> None:
    store = MemoryBankStore(tmp_path)
    event = MemoryEvent(content="test", type="reminder")
    with pytest.raises(RuntimeError, match="embedding_client required"):
        await store.write(event)


# --- get_history ---


@pytest.mark.asyncio
async def test_get_history(tmp_store: MemoryBankStore) -> None:
    await tmp_store.write_interaction("test", "response")
    history = await tmp_store.get_history(limit=10)
    assert len(history) >= 1
    assert isinstance(history[0], MemoryEvent)


@pytest.mark.asyncio
async def test_get_history_filters_daily_summary(
    tmp_path: Path,
) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store.write_interaction("hello", "world")
    meta = store._index.get_metadata("default")
    meta[0]["type"] = "daily_summary"
    history = await store.get_history()
    assert len(history) == 0


# --- get_event_type ---


@pytest.mark.asyncio
async def test_get_event_type(tmp_store: MemoryBankStore) -> None:
    result = await tmp_store.write_interaction("hello", "world")
    et = await tmp_store.get_event_type(result.event_id)
    assert et == "reminder"


@pytest.mark.asyncio
async def test_get_event_type_none_for_missing(
    tmp_store: MemoryBankStore,
) -> None:
    t = await tmp_store.get_event_type("999")
    assert t is None


@pytest.mark.asyncio
async def test_get_event_type_invalid_id(
    tmp_store: MemoryBankStore,
) -> None:
    t = await tmp_store.get_event_type("not_a_number")
    assert t is None


# --- update_feedback ---


@pytest.mark.asyncio
async def test_update_feedback(tmp_store: MemoryBankStore) -> None:
    from app.memory.schemas import FeedbackData

    fb = FeedbackData(action="accept")
    await tmp_store.update_feedback("evt_1", fb)


# --- _ensure_loaded ---


@pytest.mark.asyncio
async def test_ensure_loaded_once(tmp_store: MemoryBankStore) -> None:
    assert tmp_store._loaded is False
    await tmp_store.write_interaction("a", "b")
    assert tmp_store._loaded is True


# --- forgetting ---


@pytest.mark.asyncio
async def test_forgetting_enabled_removes_old_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORYBANK_ENABLE_FORGETTING", "1")
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store._ensure_loaded()

    text = "old entry"
    vec = await emb.encode(text)
    await store._index.add_vector(
        "default",
        text,
        vec,
        "2020-01-01T00:00:00",
        {"source": "2020-01-01"},
    )
    await store._index.save("default")
    assert store._index.total("default") == 1

    await store.write_interaction("hello", "world")
    await store.search("hello")

    assert store._index.total("default") == 1


@pytest.mark.asyncio
async def test_forgetting_disabled_keeps_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORYBANK_ENABLE_FORGETTING", "0")
    emb = _make_embedding()
    store = MemoryBankStore(
        tmp_path,
        embedding_model=emb,
        reference_date="2099-01-01",
    )
    await store.write_interaction("hello", "world")
    assert store._index.total("default") == 1
    await store._apply_forget("default")
    assert store._index.total("default") == 1


# --- background_summarize ---


@pytest.mark.asyncio
async def test_background_summarize_creates_daily_summary(
    full_store: MemoryBankStore,
) -> None:
    await full_store.write_interaction("hello", "world")
    await asyncio.sleep(0.1)
    bg_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if bg_tasks:
        await asyncio.gather(*bg_tasks, return_exceptions=True)
    meta = full_store._index.get_metadata("default")
    types = [m.get("type") for m in meta]
    assert "daily_summary" in types


# --- multi-user end-to-end ---


@pytest.mark.asyncio
async def test_multi_user_write_and_search(tmp_path: Path) -> None:
    emb = _make_embedding()
    store = MemoryBankStore(tmp_path, embedding_model=emb)
    await store.write_interaction("alice likes jazz", "ok", user_id="alice")
    await store.write_interaction("bob likes rock", "ok", user_id="bob")
    res_alice = await store.search("jazz", top_k=5, user_id="alice")
    res_bob = await store.search("rock", top_k=5, user_id="bob")
    assert len(res_alice) >= 1
    assert len(res_bob) >= 1
    assert store._index.total("alice") == 1
    assert store._index.total("bob") == 1


# --- write_interaction with custom event_type ---


@pytest.mark.asyncio
async def test_write_interaction_custom_event_type(
    tmp_store: MemoryBankStore,
) -> None:
    result = await tmp_store.write_interaction("hello", "world", event_type="custom")
    et = await tmp_store.get_event_type(result.event_id)
    assert et == "custom"
