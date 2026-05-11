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
@pytest.mark.embedding
@pytest.mark.usefixtures("llm_provider")
class TestMemoryModuleFacade:
    """MemoryModule Facade 接口测试.

    使用 usefixtures("llm_provider") 确保 LLM 配置可用，
    因为 MemoryBankStore.requires_chat=True 会惰性初始化 ChatModel。
    """

    async def test_write_and_get_history(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 write 和 get_history 基本流程."""
        await mm.write(MemoryEvent(content="事件"))
        history = await mm.get_history()
        assert len(history) == 1
        assert isinstance(history[0], MemoryEvent)

    async def test_search_routes_to_memory_bank(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 search 路由到记忆库并返回 SearchResult."""
        await mm.write(MemoryEvent(content="测试事件"))
        results = await mm.search("测试", mode=MemoryMode.MEMORY_BANK)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    async def test_write_interaction_returns_interaction_result(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 write_interaction 返回 InteractionResult."""
        result = await mm.write_interaction("提醒我开会", "好的")
        assert isinstance(result, InteractionResult)
        assert result.event_id != ""

    async def test_search_returns_public_objects(
        self,
        mm: MemoryModule,
    ) -> None:
        """验证 search 返回的对象可转换为公共格式."""
        await mm.write(MemoryEvent(content="特殊关键词事件"))
        results = await mm.search("特殊关键词", mode=MemoryMode.MEMORY_BANK)
        assert all(isinstance(r, SearchResult) for r in results)
        pub = results[0].to_public()
        assert "score" not in pub
