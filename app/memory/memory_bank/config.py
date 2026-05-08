"""MemoryBank 集中配置模型。"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryBankConfig(BaseSettings):
    """MemoryBank 全部可配置参数，环境变量前缀 MEMORYBANK_。"""

    model_config = SettingsConfigDict(env_prefix="MEMORYBANK_", case_sensitive=False)

    # ── 遗忘 ──
    enable_forgetting: bool = False
    forget_mode: Literal["deterministic", "probabilistic"] = "deterministic"
    soft_forget_threshold: float = 0.15
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0
    seed: int | None = None

    # ── 检索 ──
    chunk_size: int | None = None  # None → 自适应 P90×3
    default_chunk_size: int = 1500  # 自适应回退值
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    # ── 摘要 ──
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    # ── 嵌入 ──
    embedding_dim: int = 1536  # 首次 add_vector 后由实际向量维度覆盖；BGE-M3 为 1024

    # ── 关闭 ──
    shutdown_timeout_seconds: float = 30.0

    # ── 外部注入（非环境变量） ──
    reference_date: str | None = None
