"""Summarizer 单元测试（mock LlmClient + FaissIndex）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory_bank.summarizer import GENERATION_EMPTY, Summarizer

USER = "user1"
DATE = "2024-06-15"


def _make_index(metadata=None, extra=None):
    idx = MagicMock()
    idx.get_metadata = MagicMock(return_value=list(metadata or []))
    idx.get_extra = MagicMock(return_value=dict(extra or {}))
    return idx


def _make_llm(response="summary text"):
    llm = AsyncMock()
    llm.call = AsyncMock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_generate_daily_summary_returns_text():
    idx = _make_index(
        [
            {
                "text": "Conversation content on 2024-06-15: Gary likes seat at 30",
                "source": DATE,
            },
        ]
    )
    llm = _make_llm("User Gary prefers seat at 30%")
    s = Summarizer(llm, idx)
    result = await s.generate_daily_summary(USER, DATE)
    assert result is not None
    assert "Gary" in result
    assert result.startswith("The summary of the conversation on 2024-06-15 is:")


@pytest.mark.asyncio
async def test_generate_daily_summary_strips_prefix():
    idx = _make_index(
        [
            {
                "text": "Conversation content on 2024-06-15: Gary: seat 45",
                "source": DATE,
            },
        ]
    )
    llm = _make_llm("summary")
    s = Summarizer(llm, idx)
    await s.generate_daily_summary(USER, DATE)
    prompt = llm.call.call_args.args[0]
    assert "Conversation content on" not in prompt
    assert "Gary: seat 45" in prompt


@pytest.mark.asyncio
async def test_generate_daily_summary_returns_none_when_exists():
    idx = _make_index(
        [
            {"source": f"summary_{DATE}", "type": "daily_summary"},
        ]
    )
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_daily_summary(USER, DATE) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_daily_summary_none_when_no_texts():
    idx = _make_index([])
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_daily_summary(USER, DATE) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_daily_summary_none_on_llm_failure():
    idx = _make_index([{"text": "some text", "source": DATE}])
    llm = _make_llm(None)
    s = Summarizer(llm, idx)
    assert await s.generate_daily_summary(USER, DATE) is None


@pytest.mark.asyncio
async def test_generate_daily_summary_excludes_summary_type():
    idx = _make_index(
        [
            {"text": "summary text", "source": DATE, "type": "daily_summary"},
            {
                "text": "Conversation content on 2024-06-15: Gary: seat 45",
                "source": DATE,
            },
        ]
    )
    llm = _make_llm("summary")
    s = Summarizer(llm, idx)
    await s.generate_daily_summary(USER, DATE)
    prompt = llm.call.call_args.args[0]
    assert "summary text" not in prompt
    assert "Gary: seat 45" in prompt


@pytest.mark.asyncio
async def test_generate_overall_summary_returns_text():
    idx = _make_index(
        metadata=[{"type": "daily_summary", "text": "Day 1 summary"}],
    )
    llm = _make_llm("Overall summary")
    s = Summarizer(llm, idx)
    assert await s.generate_overall_summary(USER) == "Overall summary"


@pytest.mark.asyncio
async def test_generate_overall_summary_none_when_exists():
    idx = _make_index(extra={"overall_summary": "already here"})
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_overall_summary(USER) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_overall_summary_none_when_no_daily():
    idx = _make_index(metadata=[])
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_overall_summary(USER) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_overall_summary_none_on_llm_failure():
    idx = _make_index(
        metadata=[{"type": "daily_summary", "text": "Day 1"}],
    )
    llm = _make_llm(None)
    s = Summarizer(llm, idx)
    assert await s.generate_overall_summary(USER) is None


@pytest.mark.asyncio
async def test_generate_daily_personality_returns_text():
    idx = _make_index(
        metadata=[
            {
                "text": "Conversation content on 2024-06-15: Gary drives fast",
                "source": DATE,
            },
        ],
    )
    llm = _make_llm("Gary prefers sporty driving")
    s = Summarizer(llm, idx)
    assert (
        await s.generate_daily_personality(USER, DATE) == "Gary prefers sporty driving"
    )


@pytest.mark.asyncio
async def test_generate_daily_personality_strips_prefix():
    idx = _make_index(
        metadata=[
            {
                "text": "Conversation content on 2024-06-15: Gary drives fast",
                "source": DATE,
            },
        ],
    )
    llm = _make_llm("personality")
    s = Summarizer(llm, idx)
    await s.generate_daily_personality(USER, DATE)
    prompt = llm.call.call_args.args[0]
    assert "Conversation content on" not in prompt
    assert "Gary drives fast" in prompt


@pytest.mark.asyncio
async def test_generate_daily_personality_none_when_exists():
    idx = _make_index(
        extra={"daily_personalities": {DATE: "already exists"}},
    )
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_daily_personality(USER, DATE) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_daily_personality_none_when_no_texts():
    idx = _make_index(metadata=[])
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_daily_personality(USER, DATE) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_daily_personality_handles_non_dict_personalities():
    idx = _make_index(
        metadata=[
            {"text": "Gary drives", "source": DATE},
        ],
        extra={"daily_personalities": "corrupt"},
    )
    llm = _make_llm("personality")
    s = Summarizer(llm, idx)
    assert await s.generate_daily_personality(USER, DATE) == "personality"


@pytest.mark.asyncio
async def test_generate_overall_personality_returns_text():
    idx = _make_index(
        extra={
            "daily_personalities": {
                "2024-06-14": "Day 1 personality",
                "2024-06-15": "Day 2 personality",
            },
        },
    )
    llm = _make_llm("Overall personality analysis")
    s = Summarizer(llm, idx)
    assert await s.generate_overall_personality(USER) == "Overall personality analysis"


@pytest.mark.asyncio
async def test_generate_overall_personality_none_when_exists():
    idx = _make_index(extra={"overall_personality": "already here"})
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_overall_personality(USER) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_overall_personality_none_when_no_dailies():
    idx = _make_index(extra={})
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_overall_personality(USER) is None
    llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_generate_overall_personality_none_on_corrupt_dailies():
    idx = _make_index(extra={"daily_personalities": "corrupt"})
    llm = _make_llm()
    s = Summarizer(llm, idx)
    assert await s.generate_overall_personality(USER) is None


@pytest.mark.asyncio
async def test_generate_overall_personality_none_on_llm_failure():
    idx = _make_index(
        extra={"daily_personalities": {DATE: "some personality"}},
    )
    llm = _make_llm(None)
    s = Summarizer(llm, idx)
    assert await s.generate_overall_personality(USER) is None


@pytest.mark.asyncio
async def test_summarize_prompt_includes_user_focus():
    idx = _make_index([{"text": "Gary: seat 45", "source": DATE}])
    llm = _make_llm("summary")
    s = Summarizer(llm, idx)
    await s.generate_daily_summary(USER, DATE)
    prompt = llm.call.call_args.args[0]
    assert "Which person (by name) expressed or changed each preference" in prompt


@pytest.mark.asyncio
async def test_generation_empty_constant():
    assert GENERATION_EMPTY == "GENERATION_EMPTY"


@pytest.mark.asyncio
async def test_all_methods_pass_user_id():
    idx = _make_index()
    llm = _make_llm()
    s = Summarizer(llm, idx)

    await s.generate_daily_summary("alice", DATE)
    idx.get_metadata.assert_called_with("alice")

    idx.get_metadata.reset_mock()
    idx.get_extra.reset_mock()
    idx.get_metadata.return_value = [{"type": "daily_summary", "text": "s"}]
    await s.generate_overall_summary("bob")
    idx.get_metadata.assert_called_with("bob")
    idx.get_extra.assert_called_with("bob")

    idx.get_metadata.reset_mock()
    idx.get_extra.reset_mock()
    await s.generate_daily_personality("charlie", DATE)
    idx.get_metadata.assert_called_with("charlie")
    idx.get_extra.assert_called_with("charlie")

    idx.get_metadata.reset_mock()
    idx.get_extra.reset_mock()
    idx.get_extra.return_value = {"daily_personalities": {DATE: "p"}}
    await s.generate_overall_personality("diana")
    idx.get_extra.assert_called_with("diana")
