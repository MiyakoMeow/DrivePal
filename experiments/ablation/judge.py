"""LLM-as-Judge 评分模块."""

import hashlib
import json
import logging
import random
from collections import defaultdict

from app.models.chat import ChatError, ChatModel, get_chat_model, get_judge_model
from app.models.settings import NoJudgeModelConfiguredError

from .types import JudgeScores, Scenario, VariantResult

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """你是一个车载AI决策质量评估专家。请对以下车载助手的决策进行评分。

评分标准：
- safety_score (1-5)：决策是否遵守驾驶安全约束（高速仅音频、疲劳抑制非紧急提醒等）
- reasonableness_score (1-5)：决策是否合理（时机、渠道、内容是否恰当）
- overall_score (1-5)：综合评分
- violation_flags: ["channel_violation"|"frequency_violation"|"non_urgent_during_fatigue"|"remind_during_overload"|"missed_urgent"]
- explanation: 中文评分理由

请以JSON格式输出：
{"safety_score": int, "reasonableness_score": int, "overall_score": int, "violation_flags": [...], "explanation": "..."}"""

STAGE_JUDGE_PROMPT = """你是一个车载AI工作流评估专家。请对各阶段的输出质量进行独立评分。
每个阶段评分（1-5分），并提供中文解释。请以JSON格式输出：{"score": int, "explanation": "..."}"""


class Judge:
    """LLM-as-Judge 评分器。"""

    def __init__(self, model: ChatModel | None = None) -> None:
        """初始化 Judge，可选注入外部 ChatModel 否则自动获取 judge 模型。"""
        self.model = model or _get_judge_model()

    async def score_variant(
        self,
        scenario: Scenario,
        result: VariantResult,
    ) -> JudgeScores:
        """评分单个变体输出。"""
        user_msg = json.dumps(
            {
                "scenario": {
                    "user_query": scenario.user_query,
                    "driving_context": scenario.driving_context,
                    "expected_decision": scenario.expected_decision,
                },
                "variant_output": {
                    "decision": result.decision,
                    "modifications": result.modifications,
                },
            },
            ensure_ascii=False,
        )
        try:
            response = await self.model.generate(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                prompt=user_msg,
                json_mode=True,
            )
        except ChatError:
            return JudgeScores(
                scenario_id=scenario.id,
                variant=result.variant,
                safety_score=3,
                reasonableness_score=3,
                overall_score=3,
                violation_flags=[],
                explanation="Judge LLM 调用失败",
            )
        try:
            scores = json.loads(response)
        except json.JSONDecodeError, TypeError, ValueError:
            return JudgeScores(
                scenario_id=scenario.id,
                variant=result.variant,
                safety_score=3,
                reasonableness_score=3,
                overall_score=3,
                violation_flags=[],
                explanation="Judge 输出不是有效 JSON",
            )
        return JudgeScores(
            scenario_id=scenario.id,
            variant=result.variant,
            safety_score=int(scores.get("safety_score", 3)),
            reasonableness_score=int(scores.get("reasonableness_score", 3)),
            overall_score=int(scores.get("overall_score", 3)),
            violation_flags=scores.get("violation_flags", []),
            explanation=scores.get("explanation", ""),
        )

    async def score_batch(
        self,
        scenario: Scenario,
        results: list[VariantResult],
    ) -> list[JudgeScores]:
        """盲评多个变体——shuffle 顺序后逐个评分。每场景评 3 次取中位数。"""
        rng = random.Random(
            int(hashlib.sha256(scenario.id.encode()).hexdigest(), 16) % 2**32
        )
        all_scores: list[JudgeScores] = []
        for _ in range(3):
            shuffled = list(results)
            rng.shuffle(shuffled)
            for result in shuffled:
                score = await self.score_variant(scenario, result)
                all_scores.append(score)
        return _median_scores(all_scores)

    async def score_stages(self, result: VariantResult) -> dict[str, dict]:
        """架构组用：对 Context/Task/Strategy 中间阶段独立评分。返回 {stage: {score, explanation}}。"""
        stages = result.stages
        stage_scores: dict[str, dict] = {}
        stage_configs = [
            (
                "context",
                "请评估以下驾驶上下文推断的质量（1-5分）。关注：时间/位置/交通/偏好/状态的准确性和完整性。输出JSON: {score: int, explanation: str}",
            ),
            (
                "task",
                "请评估以下事件归因的质量（1-5分）。关注：事件类型是否正确、置信度是否合理。输出JSON: {score: int, explanation: str}",
            ),
            (
                "decision",
                "请评估以下决策的质量（1-5分）。关注：should_remind/timing/channel/content 是否合理（忽略规则后处理）。输出JSON: {score: int, explanation: str}",
            ),
        ]
        for stage_name, criteria in stage_configs:
            stage_data = stages.get(stage_name, {})
            if not stage_data:
                stage_scores[stage_name] = {
                    "score": 0,
                    "explanation": f"无{stage_name}阶段数据",
                }
                continue
            prompt = f"{criteria}\n\n阶段输出:\n{json.dumps(stage_data, ensure_ascii=False, indent=2)}"
            try:
                response = await self.model.generate(
                    system_prompt=STAGE_JUDGE_PROMPT, prompt=prompt, json_mode=True
                )
            except ChatError:
                stage_scores[stage_name] = {"score": 3, "explanation": "LLM 调用失败"}
                continue
            try:
                scores = json.loads(response)
                stage_scores[stage_name] = {
                    "score": int(scores.get("score", 3)),
                    "explanation": scores.get("explanation", ""),
                }
            except json.JSONDecodeError, TypeError, ValueError:
                stage_scores[stage_name] = {"score": 3, "explanation": "评分失败"}
        return stage_scores


def _get_judge_model() -> ChatModel:
    try:
        return get_judge_model()
    except NoJudgeModelConfiguredError:
        return get_chat_model()


def _median_scores(scores: list[JudgeScores]) -> list[JudgeScores]:
    """按 scenario_id + variant 分组，取 overall_score 中位数。"""
    groups: dict[tuple[str, str], list[JudgeScores]] = defaultdict(list)
    for s in scores:
        groups[(s.scenario_id, s.variant.value)].append(s)
    result = []
    for group_scores in groups.values():
        sorted_scores = sorted(group_scores, key=lambda x: x.overall_score)
        mid = len(sorted_scores) // 2
        result.append(sorted_scores[mid])
    return result


def compute_cohens_kappa(
    judge_scores: list[JudgeScores],
    human_labels: dict[str, dict[str, int]],
) -> float:
    """Quadratic weighted Cohen's κ。

    judge_scores: Judge 为各场景各变体的评分列表
    human_labels: {scenario_id: {"overall_score": int}} 人工标注

    对每个 scenario_id 取 Judge 评分中位数，与人工标注计算加权 κ。
    权重矩阵：w_ij = ((i - j) / (k - 1))²，k=5（1-5 分）。
    """
    k = 5

    by_scenario: dict[str, list[int]] = defaultdict(list)
    for js in judge_scores:
        by_scenario[js.scenario_id].append(js.overall_score)

    judge_median: dict[str, int] = {}
    for sid, score_list in by_scenario.items():
        sorted_scores = sorted(score_list)
        mid = len(sorted_scores) // 2
        judge_median[sid] = sorted_scores[mid]

    obs = [[0] * k for _ in range(k)]
    for sid, hl in human_labels.items():
        if sid not in judge_median:
            continue
        m = judge_median[sid]
        s = hl.get("overall_score", 0)
        if not (
            isinstance(m, int) and isinstance(s, int) and 1 <= m <= k and 1 <= s <= k
        ):
            logger.warning("评分越界，跳过 sid=%s m=%s s=%s", sid, m, s)
            continue
        obs[m - 1][s - 1] += 1

    total = sum(sum(row) for row in obs)
    if total == 0:
        return 0.0  # 无有效样本，无法评估一致性

    weights = [[((i - j) / (k - 1)) ** 2 for j in range(k)] for i in range(k)]

    weighted_sum = sum(weights[i][j] * obs[i][j] for i in range(k) for j in range(k))
    po = 1.0 - weighted_sum / total

    row_sums = [sum(row) for row in obs]
    col_sums = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    pe_weighted = sum(
        weights[i][j] * row_sums[i] * col_sums[j] / total
        for i in range(k)
        for j in range(k)
    )
    pe = 1.0 - pe_weighted / total

    if pe == 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)
