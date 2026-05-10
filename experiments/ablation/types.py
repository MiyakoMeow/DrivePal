"""消融实验数据类型."""

from dataclasses import dataclass, field
from enum import StrEnum


class Variant(StrEnum):
    """消融变体枚举."""

    FULL = "full"
    NO_RULES = "no-rules"
    NO_PROB = "no-prob"
    SINGLE_LLM = "single-llm"
    NO_FEEDBACK = "no-feedback"


@dataclass
class Scenario:
    """测试场景——包含驾驶上下文、用户查询、期望决策."""

    id: str
    driving_context: dict
    user_query: str
    expected_decision: dict
    expected_task_type: str
    safety_relevant: bool
    scenario_type: str


@dataclass
class VariantResult:
    """单个变体的运行结果——含决策、阶段输出、耗时."""

    scenario_id: str
    variant: Variant
    decision: dict
    result_text: str
    event_id: str | None
    stages: dict
    latency_ms: float
    modifications: list[str] = field(default_factory=list)
    round_index: int = 0


@dataclass
class JudgeScores:
    """LLM-as-Judge 评分结果."""

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
