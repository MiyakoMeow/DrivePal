"""MemoryBank 集中配置模型。"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .index import FaissIndex


class MemoryBankConfig(BaseSettings):
    """MemoryBank 全部可配置参数，环境变量前缀 MEMORYBANK_。"""

    model_config = SettingsConfigDict(env_prefix="MEMORYBANK_", case_sensitive=False)

    # ── 遗忘 ──
    enable_forgetting: bool = False
    forget_mode: Literal["deterministic", "probabilistic"] = "deterministic"
    soft_forget_threshold: float = 0.3
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0
    seed: int | None = None

    # ── 检索 ──
    chunk_size: int | None = None
    default_chunk_size: int = 1500
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    # ── 记忆强度上限，防止无限回忆强化导致旧条目永不遗忘 ──
    max_memory_strength: int = 10

    @field_validator("max_memory_strength")
    @classmethod
    def _guard_max_memory_strength_positive(cls, v: int) -> int:
        if v < 1:
            return 10
        return v

    # ── 检索加权公式 α 系数（语义相似度 vs 记忆留存率权衡）──
    retrieval_alpha: float = 0.7

    @field_validator("retrieval_alpha")
    @classmethod
    def _guard_retrieval_alpha_range(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            return 0.7
        return v

    # ── BM25 稀疏检索回退——FAISS 密集检索失效时的兜底 ──
    bm25_fallback_enabled: bool = True
    bm25_fallback_threshold: float = 0.5

    @field_validator("bm25_fallback_threshold")
    @classmethod
    def _guard_bm25_threshold_range(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            return 0.5
        return v

    # ── FAISS 索引类型选择：flat 精确检索 / ivf_flat 近似检索 ──
    index_type: Literal["flat", "ivf_flat"] = "flat"
    ivf_nlist: int = 128

    @field_validator("ivf_nlist")
    @classmethod
    def _guard_ivf_nlist_positive(cls, v: int) -> int:
        if v < 1:
            return 128
        return v

    @field_validator("coarse_search_factor")
    @classmethod
    def _guard_coarse_factor(cls, v: int) -> int:
        if v <= 0:
            return 4
        return v

    @field_validator("forgetting_time_scale")
    @classmethod
    def _guard_time_scale_positive(cls, v: float) -> float:
        if v <= 0:
            return 1.0
        return v

    # ── LLM ──
    llm_max_retries: int = 3
    llm_trim_start: int = 1800
    llm_trim_step: int = 200
    llm_trim_min: int = 500
    llm_anchor_user: str = (
        "Hello! Please help me summarize the content of the conversation."
    )
    llm_anchor_assistant: str = "Sure, I will do my best to assist you."
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None

    @field_validator("llm_max_retries")
    @classmethod
    def _guard_llm_retries_positive(cls, v: int) -> int:
        if v < 1:
            return 3
        return v

    @field_validator("llm_trim_min")
    @classmethod
    def _guard_trim_min_positive(cls, v: int) -> int:
        if v < 1:
            return 500
        return v

    # ── 摘要 ──
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    # ── 嵌入 ──
    embedding_dim: int = 1536
    embedding_batch_size: int = 100

    @field_validator("embedding_batch_size")
    @classmethod
    def _guard_embedding_batch_positive(cls, v: int) -> int:
        if v < 1:
            return 100
        return v

    # ── 持久化 ──
    save_interval_seconds: float = 30.0

    @field_validator("save_interval_seconds")
    @classmethod
    def _guard_save_interval_positive(cls, v: float) -> float:
        if v <= 0:
            return 30.0
        return v

    # ── 参考日期 ──
    reference_date: str | None = None
    reference_date_auto: bool = False

    @field_validator("reference_date")
    @classmethod
    def _guard_reference_date_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError, TypeError:
            logging.getLogger(__name__).warning(
                "Invalid reference_date=%r, falling back to today", v
            )
            return datetime.now(UTC).strftime("%Y-%m-%d")
        return v

    # ── 关闭 ──
    shutdown_timeout_seconds: float = 30.0


def resolve_reference_date(
    config: MemoryBankConfig,
    index: FaissIndex,
) -> str:
    """参考日期解析。优先级：config.reference_date > auto 推算 > UTC 当天。"""
    if config.reference_date:
        return config.reference_date
    if config.reference_date_auto:
        return index.compute_reference_date()
    return datetime.now(UTC).strftime("%Y-%m-%d")
