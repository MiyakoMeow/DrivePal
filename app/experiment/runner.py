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
    """计算时间衰减权重，使用指数衰减公式"""
    now = datetime.now()
    days_ago = (now - event_time).total_seconds() / (24 * 3600)
    if days_ago < 0:
        return 1.0  # 未来事件权重最高
    return math.exp(-days_ago / half_life_days)


def _compute_context_weight(current_turn: int, last_turn: Optional[int]) -> float:
    """计算多轮对话的上下文权重"""
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
    "不",
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
    """基于规则的语义准确率评估

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
        chinese_chars = re.findall(r"[\u4e00-\u9fff]+", text.lower())
        english_words = re.findall(r"[a-zA-Z]+", text.lower())
        chinese_set = set("".join(chinese_chars))
        english_set = set(english_words)
        return chinese_set | english_set

    input_words = split_words(input_text)
    output_words = split_words(output)
    overlap = len(input_words & output_words)
    if overlap > 0:
        score += min(0.4, overlap * 0.1)

    return min(1.0, score)


class ExperimentRunner:
    def __init__(self, data_dir: str = "data", config_dir: str = "config"):
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
        self, test_cases: List[Dict[str, str]], methods: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """运行对比实验"""
        if methods is None:
            methods = ["keyword", "llm_only", "embeddings"]

        results = {
            "timestamp": datetime.now().isoformat(),
            "test_cases": len(test_cases),
            "methods": methods,
            "metrics": {},
        }

        for method in methods:
            method_results = self._run_method(method, test_cases)
            results["metrics"][method] = method_results

        self._save_results(results)
        return results

    def _run_method(self, method: str, test_cases: List[Dict]) -> Dict:
        """运行单个方法的实验"""
        workflow = create_workflow(self.data_dir, memory_mode=method)

        latencies = []
        task_completions = []
        semantic_accuracies = []
        context_relatedness_scores = []

        for case in test_cases:
            start_time = time.time()
            try:
                result, event_id = workflow.run(case["input"])
                elapsed = (time.time() - start_time) * 1000

                latencies.append(elapsed)
                task_completions.append(1)

                actual_output = result if result else self._get_latest_output()

                accuracy = self._evaluate_semantic_accuracy(
                    case["input"], case["type"], actual_output
                )
                semantic_accuracies.append(accuracy)

                relatedness = self._evaluate_context_relatedness(
                    case["input"], case["type"], actual_output
                )
                context_relatedness_scores.append(relatedness)

            except Exception as e:
                logger.warning(
                    f"Experiment run failed for case '{case.get('input', 'unknown')}': {e}"
                )
                latencies.append(0)
                task_completions.append(0)
                semantic_accuracies.append(0)
                context_relatedness_scores.append(0)

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
        }

    def _get_latest_output(self) -> str:
        """从存储中获取最新的输出结果"""
        events_store = JSONStore(self.data_dir, "events.json", list)
        events = events_store.read()
        if events and len(events) > 0:
            last_event = events[-1]
            return last_event.get("decision", {}).get("content", "")
        return ""

    def _evaluate_semantic_accuracy(
        self, input_text: str, expected_type: str, output: str
    ) -> float:
        """评估语义理解准确率（委托给模块级函数）"""
        return _evaluate_semantic_accuracy(input_text, expected_type, output)

    def _extract_task_indicators(self, output: str) -> Dict[str, int]:
        """动态提取任务类型指示词"""
        indicators = {}

        # 任务类型关键词（可配置，从外部获取）
        type_patterns = self._get_type_patterns()

        for task_type, patterns in type_patterns.items():
            count = sum(1 for p in patterns if p in output)
            if count > 0:
                indicators[task_type] = count

        return indicators

    def _get_type_patterns(self) -> Dict[str, List[str]]:
        """获取任务类型模式 - 从配置文件读取"""
        config = self._load_evaluation_config()
        return config.get(
            "type_patterns",
            {
                "meeting": ["会议", "meeting", "评审", "沟通会"],
                "travel": ["出差", "travel", "行程"],
                "shopping": ["购物", "shopping", "采购"],
                "contact": ["联系", "contact", "电话"],
            },
        )

    def _evaluate_context_relatedness(
        self, input_text: str, expected_type: str, output: str
    ) -> float:
        """评估上下文相关度

        使用更通用的方法：检查输出是否提及任务相关概念
        """
        output_lower = output.lower()

        # 通用任务相关概念（从配置获取）
        task_concepts = self._get_task_concepts()
        concepts = task_concepts.get(expected_type, [])

        relevant = sum(1 for c in concepts if c in output_lower)
        relatedness = min(relevant / max(len(concepts), 1), 1.0)

        return relatedness

    def _get_task_concepts(self) -> Dict[str, List[str]]:
        """获取任务相关概念 - 从配置文件读取"""
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
        """生成对比报告"""
        results_store = JSONStore(self.data_dir, "experiment_results.json", list)
        results = results_store.read()

        if not results:
            return "暂无实验数据"

        latest = results[-1]
        report = "# 实验对比报告\n\n"
        report += f"时间: {latest['timestamp']}\n\n"
        report += f"测试用例数: {latest['test_cases']}\n\n"
        report += "## 方法对比\n\n"

        for method, metrics in latest["metrics"].items():
            report += f"### {method}\n"
            report += f"- 平均延迟: {metrics['avg_latency_ms']:.2f}ms\n"
            report += f"- 任务完成率: {metrics['task_completion_rate'] * 100:.1f}%\n"
            report += (
                f"- 语义理解准确率: {metrics.get('semantic_accuracy', 0) * 100:.1f}%\n"
            )
            report += f"- 上下文相关度: {metrics.get('context_relatedness', 0) * 100:.1f}%\n\n"

        return report
