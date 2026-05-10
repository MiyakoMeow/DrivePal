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
    def total(self) -> int:
        """返回索引中向量总数。"""
        ...

    def get_metadata(self) -> list[dict]:
        """返回所有元数据列表。"""
        ...

    async def search(self, query_emb: list[float], top_k: int) -> list[dict]:
        """检索最相似的 top_k 条记忆。"""
        ...

    def get_extra(self) -> dict:
        """返回额外元数据（总体摘要/人格）。"""
        ...
