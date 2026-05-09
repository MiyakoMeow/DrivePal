"""消融实验数据类型."""
from dataclasses import dataclass, field
from enum import Enum


class Variant(str, Enum):
    FULL = "full"
    NO_RULES = "no-rules"
    NO_PROB = "no-prob"
    SINGLE_LLM = "single-llm"
    NO_FEEDBACK = "no-feedback"


@dataclass
class TestScenario:
    id: str
    driving_context: dict
    user_query: str
    expected_decision: dict
    expected_task_type: str
    safety_relevant: bool
    scenario_type: str


@dataclass
class VariantResult:
    scenario_id: str
    variant: Variant
    decision: dict
    result_text: str
    event_id: str | None
    stages: dict
    latency_ms: float
    modifications: list[str] = field(default_factory=list)


@dataclass
class JudgeScores:
    scenario_id: str
    variant: Variant
    safety_score: int
    reasonableness_score: int
    overall_score: int
    violation_flags: list[str]
    explanation: str


@dataclass
class GroupResult:
    """一组实验的完整结果."""

    group: str
    variant_results: list[VariantResult]
    judge_scores: list[JudgeScores]
    metrics: dict
