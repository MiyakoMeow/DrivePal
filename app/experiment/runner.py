"""实验运行模块，提供多记忆检索方法的对比实验与评估功能."""

import logging
import re
import time
import json
import os
import math
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.agents.workflow import create_workflow
from app.storage.json_store import JSONStore

logger = logging.getLogger(__name__)


def _compute_time_decay(event_time: datetime, half_life_days: float = 7.0) -> float:
    """计算时间衰减权重，使用指数衰减公式."""
    now = datetime.now()
    days_ago = (now - event_time).total_seconds() / (24 * 3600)
    if days_ago < 0:
        return 1.0  # 未来事件权重最高
    return math.exp(-days_ago / half_life_days)


def _compute_context_weight(current_turn: int, last_turn: Optional[int]) -> float:
    """计算多轮对话的上下文权重."""
    if last_turn is None:
        return 1.0
    if current_turn == last_turn:
        return 1.0
    turn_diff = current_turn - last_turn
    if turn_diff <= 0:
        return 1.0
    if turn_diff == 1:
        return 0.8
    return max(0.5, 1.0 - turn_diff * 0.2)


INTENT_KEYWORDS: Dict[str, List[str]] = {
    "schedule_check": [
        # 中文
        "时间",
        "日程",
        "安排",
        "查",
        "看",
        "几点",
        "什么时候",
        "明天",
        "今天",
        "后天",
        "这周",
        "下周",
        # 英文
        "schedule",
        "when",
        "time",
        "what",
        "check",
        "look",
        "see",
        "tomorrow",
        "today",
        "calendar",
        "appointment",
    ],
    "event_add": [
        # 中文
        "添加",
        "新建",
        "提醒",
        "记录",
        "创建",
        "加",
        "设定",
        "下午",
        "早上",
        "晚上",
        "点",
        "分钟",
        "小时",
        # 英文
        "add",
        "new",
        "remind",
        "create",
        "set",
        "schedule",
        "pm",
        "am",
        "minute",
        "hour",
    ],
    "event_delete": [
        # 中文
        "删除",
        "取消",
        "去掉",
        "移除",
        "不要",
        # 英文
        "delete",
        "cancel",
        "remove",
        "don't",
    ],
    "general": [],
}

NEGATIVE_PATTERNS = [
    "不要",
    "别",
    "取消",
    "去掉",
    "删除",
    "移除",
    "don't",
    "dont",
    "cancel",
    "remove",
    "delete",
    "stop",
    "no",
]


def _has_negative_pattern(query: str) -> bool:
    query_lower = query.lower()
    for pattern in NEGATIVE_PATTERNS:
        if pattern in query_lower:
            return True
    return False


def _infer_intent(query: str) -> str:
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if intent == "general":
            continue
        for kw in keywords:
            if kw in query_lower:
                return intent
    return "general"


def _evaluate_semantic_accuracy(
    input_text: str, expected_type: str, output: str
) -> float:
    """基于规则的语义准确率评估.

    使用 Task 1.1-1.3 添加的辅助函数。
    - 意图匹配 (40%): _infer_intent
    - 否定模式 (20%): _has_negative_pattern
    - 关键词重叠 (40%): 简单交集
    """
    score = 0.0

    # 1. 意图匹配 (40%)
    inferred = _infer_intent(input_text)
    if inferred == expected_type:
        score += 0.4

    # 2. 否定模式处理 (20%)
    has_neg = _has_negative_pattern(input_text)
    neg_keywords = ["取消", "删除", "不要", "别", "don't", "cancel"]
    output_has_neg = any(kw in output.lower() for kw in neg_keywords)
    if has_neg == output_has_neg:
        score += 0.2

    # 3. 关键词重叠 (40%)
    def split_words(text: str) -> set:
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        english_words = set(re.findall(r"[a-zA-Z]+", text.lower()))
        chinese_bigrams = {
            chinese_chars[i] + chinese_chars[i + 1]
            for i in range(len(chinese_chars) - 1)
        }
        return chinese_bigrams | english_words

    input_words = split_words(input_text)
    output_words = split_words(output)
    overlap = len(input_words & output_words)
    if overlap > 0:
        score += min(0.4, overlap * 0.05)

    return min(1.0, score)


class ExperimentRunner:
    """实验对比运行器，支持多种记忆检索方法的基准测试."""

    def __init__(self, data_dir: str = "data", config_dir: str = "config"):
        """初始化实验运行器."""
        self.data_dir = data_dir
        self.config_dir = config_dir
        self._evaluation_config = None

    def _load_evaluation_config(self) -> Dict:
        if self._evaluation_config is None:
            config_path = os.path.join(self.config_dir, "evaluation_config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._evaluation_config = json.load(f)
            else:
                self._evaluation_config = {}
        return self._evaluation_config

    def run_comparison(
        self,
        test_cases: List[Dict[str, str]],
        methods: Optional[List[str]] = None,
        data_dir: str | None = None,
        seed: int | None = None,
    ) -> Dict[str, Any]:
        """运行多方法对比实验并返回评估结果."""
        if not test_cases:
            raise ValueError("test_cases cannot be empty")
        for tc in test_cases:
            if not isinstance(tc, dict):
                raise ValueError(f"test_case must be dict, got {type(tc)}")
            if "input" not in tc:
                raise ValueError("test_case missing required field 'input'")
        valid_methods = {"keyword", "llm_only", "embeddings", "memorybank"}
        if methods is None:
            methods = ["keyword", "llm_only", "embeddings", "memorybank"]
        else:
            invalid = set(methods) - valid_methods
            if invalid:
                raise ValueError(f"Invalid methods: {invalid}")
        results = {
            "timestamp": datetime.now().isoformat(),
            "test_cases": len(test_cases),
            "methods": methods,
            "seed": seed,
            "metrics": {},
        }
        for method in methods:
            method_results = self._run_method(method, test_cases, data_dir=data_dir)
            results["metrics"][method] = method_results
        self._save_results(results)
        return results

    def _run_method(
        self, method: str, test_cases: List[Dict], data_dir: str | None = None
    ) -> Dict:
        effective_data_dir = data_dir if data_dir is not None else self.data_dir
        workflow = create_workflow(effective_data_dir, memory_mode=method)

        latencies = []
        task_completions = []
        semantic_accuracies = []
        context_relatedness_scores = []
        per_case = []

        for case in test_cases:
            start_time = time.time()
            try:
                result, event_id = workflow.run(case["input"])
                elapsed = (time.time() - start_time) * 1000
                latencies.append(elapsed)
                task_completions.append(1)
                actual_output = self._extract_scoring_output(result, effective_data_dir)
                accuracy = self._evaluate_semantic_accuracy(
                    case["input"], case["type"], actual_output
                )
                semantic_accuracies.append(accuracy)
                relatedness = self._evaluate_context_relatedness(
                    case["input"], case["type"], actual_output
                )
                context_relatedness_scores.append(relatedness)
                per_case.append(
                    {
                        "input": case["input"],
                        "type": case["type"],
                        "output": actual_output[:200],
                        "latency_ms": elapsed,
                        "semantic_accuracy": accuracy,
                        "context_relatedness": relatedness,
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Experiment run failed for case '{case.get('input', 'unknown')}': {e}"
                )
                latencies.append(0)
                task_completions.append(0)
                semantic_accuracies.append(0)
                context_relatedness_scores.append(0)
                per_case.append(
                    {
                        "input": case["input"],
                        "type": case["type"],
                        "output": "",
                        "latency_ms": 0,
                        "semantic_accuracy": 0,
                        "context_relatedness": 0,
                        "error": str(e),
                    }
                )

        return {
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "task_completion_rate": sum(task_completions) / len(task_completions)
            if task_completions
            else 0,
            "semantic_accuracy": sum(semantic_accuracies) / len(semantic_accuracies)
            if semantic_accuracies
            else 0,
            "context_relatedness": sum(context_relatedness_scores)
            / len(context_relatedness_scores)
            if context_relatedness_scores
            else 0,
            "per_case": per_case,
        }

    def _get_latest_output(self, data_dir: str | None = None) -> str:
        effective_dir = data_dir if data_dir is not None else self.data_dir
        events_store = JSONStore(effective_dir, "events.json", list)
        events = events_store.read()
        if events and len(events) > 0:
            last_event = events[-1]
            return last_event.get("decision", {}).get("content", "")
        return ""

    def _extract_scoring_output(self, result: str, data_dir: str | None = None) -> str:
        effective_dir = data_dir if data_dir is not None else self.data_dir
        events_store = JSONStore(effective_dir, "events.json", list)
        events = events_store.read()
        if events:
            last_event = events[-1]
            decision = last_event.get("decision", {})
            if isinstance(decision, str):
                return decision
            content = decision.get("remind_content") or decision.get("content")
            if content:
                return content
            reasoning = decision.get("reasoning", "")
            if reasoning:
                return reasoning
            raw = decision.get("raw", "")
            if raw:
                return raw
        return result if result else self._get_latest_output(data_dir=effective_dir)

    def _evaluate_semantic_accuracy(
        self, input_text: str, expected_type: str, output: str
    ) -> float:
        """评估语义理解准确率（委托给模块级函数）.

        根据意图匹配、否定模式处理和关键词重叠综合打分.
        """
        return _evaluate_semantic_accuracy(input_text, expected_type, output)

    def _evaluate_context_relatedness(
        self, input_text: str, expected_type: str, output: str
    ) -> float:
        """评估输出与任务类型的上下文相关度."""
        output_lower = output.lower()
        task_concepts = self._get_task_concepts()
        concepts = task_concepts.get(expected_type, [])
        if not concepts:
            return 0.5
        relevant = sum(1 for c in concepts if c in output_lower)
        relatedness = min(relevant / max(len(concepts), 1), 1.0)
        return relatedness

    def _get_task_concepts(self) -> Dict[str, List[str]]:
        """获取各任务类型的相关概念词配置."""
        config = self._load_evaluation_config()
        return config.get(
            "task_concepts",
            {
                "meeting": ["时间", "提醒", "会议", "地点", "确认", "安排"],
                "travel": ["时间", "提醒", "行程", "地址", "确认", "安排", "出差"],
                "shopping": ["时间", "提醒", "购物", "确认", "安排", "买"],
                "contact": ["时间", "提醒", "联系", "确认", "安排"],
            },
        )

    def _save_results(self, results: Dict):
        results_store = JSONStore(self.data_dir, "experiment_results.json", list)
        results_store.append(results)

    def generate_report(self) -> str:
        """生成实验对比报告的Markdown文本."""
        results_store = JSONStore(self.data_dir, "experiment_results.json", list)
        results = results_store.read()
        if not results:
            return "暂无实验数据"
        latest = results[-1]
        report = "# 实验对比报告\n\n"
        report += f"时间: {latest['timestamp']}\n"
        report += f"测试用例数: {latest['test_cases']}\n"
        if "seed" in latest:
            report += f"随机种子: {latest['seed']}\n"
        report += "\n## 方法对比\n\n"
        report += "| 方法 | 平均延迟(ms) | 完成率 | 语义准确率 | 上下文相关度 |\n"
        report += "|------|-------------|--------|-----------|-------------|\n"
        for method, metrics in latest["metrics"].items():
            report += f"| {method} | {metrics['avg_latency_ms']:.1f} | {metrics['task_completion_rate'] * 100:.1f}% | {metrics.get('semantic_accuracy', 0) * 100:.1f}% | {metrics.get('context_relatedness', 0) * 100:.1f}% |\n"
        return report
