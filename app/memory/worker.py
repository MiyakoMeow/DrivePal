"""后台记忆维护任务调度器。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.interfaces import SummarizationService, VectorIndex
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class BackgroundWorker:
    """后台记忆维护任务调度器。

    从 MemoryBankStore._background_summarize 提取，统一管理 async task 生命周期。
    错误内部 logging 记录，不 propagation 到 caller。
    """

    def __init__(
        self,
        index: VectorIndex,
        summarizer: SummarizationService | None = None,
        encoder: EmbeddingModel | None = None,
    ) -> None:
        """初始化 worker，绑定 vector index 和可选 summarizer/encoder。"""
        self._index = index
        self._summarizer = summarizer
        self._encoder = encoder
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule_summarize(self, date_key: str) -> None:
        """调度后台摘要任务。"""
        task = asyncio.create_task(self._run_summarize(date_key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """等待所有后台任务完成。"""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_summarize(self, date_key: str) -> None:
        if not self._summarizer:
            return
        try:
            text = await self._summarizer.get_daily_summary(date_key)
            if text and self._encoder:
                emb = await self._encoder.encode(text)
                await self._index.add_vector(
                    text,
                    emb,
                    f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save()
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except Exception:
            logger.exception("background summarization failed")
