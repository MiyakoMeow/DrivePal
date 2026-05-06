"""LLMJsonClient 单元测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.llm_utils import LLMJsonClient


@pytest.mark.asyncio
async def test_call_plain_json():
    """普通 JSON 字符串正常解析。"""
    model = MagicMock()
    model.generate = AsyncMock(return_value='{"key": "value"}')
    client = LLMJsonClient(model)
    result = await client.call("user prompt")
    assert result == {"key": "value", "raw": '{"key": "value"}'}
    assert "raw" in result


@pytest.mark.asyncio
async def test_call_markdown_json():
    """Markdown 代码块包裹的 JSON 正常解析。"""
    raw_text = '```json\n{"key": "value"}\n```'
    model = MagicMock()
    model.generate = AsyncMock(return_value=raw_text)
    client = LLMJsonClient(model)
    result = await client.call("user prompt")
    assert result == {"key": "value", "raw": raw_text}


@pytest.mark.asyncio
async def test_call_broken_json_returns_raw():
    """非法 JSON 回退到 {"raw": original_text}。"""
    model = MagicMock()
    model.generate = AsyncMock(return_value="not json at all")
    client = LLMJsonClient(model)
    result = await client.call("user prompt")
    assert result == {"raw": "not json at all"}


@pytest.mark.asyncio
async def test_call_non_dict_json_returns_raw():
    """JSON 非 dict 回退到 {"raw": original_text}。"""
    model = MagicMock()
    model.generate = AsyncMock(return_value='["a", "list"]')
    client = LLMJsonClient(model)
    result = await client.call("user prompt")
    assert result == {"raw": '["a", "list"]'}
