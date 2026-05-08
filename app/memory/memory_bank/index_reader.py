"""FaissIndex 只读视图 Protocol。"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class IndexReader(Protocol):
    """FaissIndex 只读视图。消费端（Summarizer / RetrievalPipeline）仅依赖此接口。

    get_metadata() 返回的每个 dict 至少含以下键：
      text, source, type, speakers, forgotten, memory_strength, last_recall_date,
      faiss_id, timestamp
    """

    @property
    def total(self) -> int: ...

    def get_metadata(self) -> list[dict]: ...

    async def search(
        self, query_emb: list[float], top_k: int
    ) -> list[dict]: ...

    def get_extra(self) -> dict: ...
