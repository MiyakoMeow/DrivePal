"""MemoChat prompt 模板测试."""

from app.memory.stores.memochat.prompts import (
    RETRIEVAL_INSTRUCTION,
    RETRIEVAL_SYSTEM,
    WRITING_INSTRUCTION,
    WRITING_SYSTEM,
)
from app.memory.stores.memochat.retriever import RetrievalMode


def test_writing_system_contains_line_placeholder() -> None:
    """WRITING_SYSTEM 包含 LINE 占位符."""
    assert "LINE" in WRITING_SYSTEM


def test_writing_instruction_contains_json_keys() -> None:
    """WRITING_INSTRUCTION 包含 JSON 键名."""
    for key in ("topic", "summary", "start", "end"):
        assert key in WRITING_INSTRUCTION


def test_retrieval_system_contains_option_placeholder() -> None:
    """RETRIEVAL_SYSTEM 包含 OPTION 占位符."""
    assert "OPTION" in RETRIEVAL_SYSTEM


def test_retrieval_instruction_mentions_noto() -> None:
    """RETRIEVAL_INSTRUCTION 包含 NOTO 选项."""
    assert "NOTO" in RETRIEVAL_INSTRUCTION


def test_retrieval_instruction_mentions_separator() -> None:
    """RETRIEVAL_INSTRUCTION 包含分隔符."""
    assert "#" in RETRIEVAL_INSTRUCTION


def test_retrieval_mode_values() -> None:
    """RetrievalMode 枚举值正确."""
    assert RetrievalMode.FULL_LLM == "full_llm"
    assert RetrievalMode.HYBRID == "hybrid"


def test_retrieval_mode_is_str() -> None:
    """RetrievalMode 枚举值是字符串."""
    assert isinstance(RetrievalMode.FULL_LLM, str)
