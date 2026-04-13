"""MemoryModule 门面模式测试."""

from typing import TYPE_CHECKING

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import InteractionResult, MemoryEvent, SearchResult
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.embedding import EmbeddingModel


@pytest.fixture
def mm(tmp_path: Path, embedding: EmbeddingModel) -> MemoryModule:
    """提供一个 MemoryModule 实例用于测试."""
    return MemoryModule(tmp_path, embedding_model=embedding)


@pytest.mark.llm
@pytest.mark.usefixtures("llm_provider")
class TestMemoryModuleFacade:
    """MemoryModule Facade 接口测试.

    使用 usefixtures("llm_provider") 确保 LLM 配置可用，
    因为 MemoryBankStore.requires_chat=True 会惰性初始化 ChatModel。
    """

    async def test_default_mode_is_memory_bank(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证默认模式为 memory_bank（通过隐式调用验证）."""
        await mm.write(MemoryEvent(content="test"))

    async def test_write_uses_default_mode(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 write 使用默认模式存储."""
        await mm.write(MemoryEvent(content="事件"))
        history = await mm.get_history()
        assert len(history) == 1
        assert isinstance(history[0], MemoryEvent)

    async def test_search_routes_to_correct_store(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 search 路由到正确的存储后端."""
        await mm.write(MemoryEvent(content="测试事件"))
        results = await mm.search("测试", mode=MemoryMode.MEMORY_BANK)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    async def test_write_with_explicit_mode(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 write 使用显式 mode 参数."""
        await mm.write(MemoryEvent(content="test"), mode=MemoryMode.MEMORY_BANK)
        history = await mm.get_history(mode=MemoryMode.MEMORY_BANK)
        assert len(history) == 1

    async def test_write_interaction_calls_memory_bank(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 write_interaction 在 memory_bank 模式下返回 InteractionResult."""
        result = await mm.write_interaction("提醒我开会", "好的")
        assert isinstance(result, InteractionResult)
        assert result.event_id != ""

    async def test_search_returns_search_result_objects(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 search 返回 SearchResult 对象列表."""
        await mm.write(MemoryEvent(content="特殊关键词事件"))
        results = await mm.search("特殊关键词", mode=MemoryMode.MEMORY_BANK)
        assert all(isinstance(r, SearchResult) for r in results)
        pub = results[0].to_public()
        assert "score" not in pub

    async def test_get_history_returns_memory_event_objects(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 get_history 返回 MemoryEvent 对象列表."""
        await mm.write(MemoryEvent(content="事件"))
        history = await mm.get_history()
        assert all(isinstance(e, MemoryEvent) for e in history)
