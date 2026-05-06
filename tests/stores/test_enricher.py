"""测试 OverallContextEnricher。"""

import pytest

from app.memory.enricher import OverallContextEnricher
from app.memory.schemas import SearchResult
from app.memory.stores.memory_bank.summarizer import GENERATION_EMPTY


class TestOverallContextEnricher:
    """给定默认 key 的 enricher。"""

    @pytest.fixture
    def enricher(self):
        """fixture: 默认 enricher。"""
        return OverallContextEnricher()

    async def test_empty_extra_returns_results_unchanged(self, enricher):
        """空 extra 时返回原结果不变。"""
        results = [SearchResult(event={"content": "a"}, score=1.0)]
        out = await enricher.enrich(results, {})
        assert out == results

    async def test_prepends_summary_when_present(self, enricher):
        """有 overall_summary 时前置到结果列表，不丢弃原有结果。"""
        results = [
            SearchResult(event={"content": "a"}, score=1.0),
            SearchResult(event={"content": "b"}, score=0.5),
            SearchResult(event={"content": "c"}, score=0.2),
        ]
        extra = {"overall_summary": "User likes sport mode"}
        out = await enricher.enrich(results, extra)
        assert len(out) == len(results) + 1
        assert "User likes sport mode" in out[0].event["content"]
        assert out[1].event["content"] == "a"
        assert out[2].event["content"] == "b"
        assert out[3].event["content"] == "c"

    async def test_skips_generation_empty(self, enricher):
        """GENERATION_EMPTY 占位符被跳过。"""
        results = [SearchResult(event={"content": "a"}, score=1.0)]
        extra = {"overall_summary": GENERATION_EMPTY}
        out = await enricher.enrich(results, extra)
        assert len(out) == 1
        assert out[0] == results[0]

    async def test_custom_keys(self):
        """自定义 key 和 label 可注入到前置内容。"""
        enricher = OverallContextEnricher(keys=[("custom_key", "Custom label")])
        results = [SearchResult(event={"content": "x"}, score=0.5)]
        extra = {"custom_key": "value"}
        out = await enricher.enrich(results, extra)
        assert "Custom label: value" in out[0].event["content"]

    async def test_multiple_keys(self):
        """多 key 合并到同一前置条目，用换行分隔。"""
        keys = [("k1", "L1"), ("k2", "L2")]
        enricher = OverallContextEnricher(keys=keys)
        results = [
            SearchResult(event={"content": "a"}, score=1.0),
            SearchResult(event={"content": "b"}, score=0.5),
            SearchResult(event={"content": "c"}, score=0.2),
        ]
        extra = {"k1": "v1", "k2": "v2"}
        out = await enricher.enrich(results, extra)
        assert len(out) == len(results) + 1
        assert "L1: v1" in out[0].event["content"]
        assert "L2: v2" in out[0].event["content"]
