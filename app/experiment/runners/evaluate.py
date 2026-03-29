"""规则评估函数（从 runner.py 迁移）."""

import json
import os
import re

INTENT_KEYWORDS: dict[str, list[str]] = {
    "schedule_check": [
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
        "删除",
        "取消",
        "去掉",
        "移除",
        "不要",
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


def infer_intent(query: str) -> str:
    """根据关键词推断用户意图."""
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if intent == "general":
            continue
        for kw in keywords:
            if kw in query_lower:
                return intent
    return "general"


def _has_negative_pattern(query: str) -> bool:
    query_lower = query.lower()
    return any(p in query_lower for p in NEGATIVE_PATTERNS)


def evaluate_semantic_accuracy(
    input_text: str, expected_type: str, output: str,
) -> float:
    """评估语义理解准确率."""
    score = 0.0

    inferred = infer_intent(input_text)
    if inferred == expected_type:
        score += 0.4

    has_neg = _has_negative_pattern(input_text)
    neg_keywords = ["取消", "删除", "不要", "别", "don't", "cancel"]
    output_has_neg = any(kw in output.lower() for kw in neg_keywords)
    if has_neg == output_has_neg:
        score += 0.2

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


_DEFAULT_TASK_CONCEPTS: dict[str, list[str]] = {
    "schedule_check": [
        "时间",
        "日程",
        "安排",
        "查询",
        "提醒",
        "会议",
        "几点",
        "什么",
    ],
    "event_add": [
        "添加",
        "创建",
        "提醒",
        "设置",
        "安排",
        "记录",
        "新建",
        "会议",
        "点",
    ],
    "event_delete": [
        "取消",
        "删除",
        "移除",
        "去掉",
        "不要",
        "no",
        "cancel",
    ],
    "general": ["好", "天气", "最近", "怎么样", "hello", "how", "今天"],
}


def _load_task_concepts(config_dir: str = "config") -> dict[str, list[str]]:
    config_path = os.path.join(config_dir, "evaluation_config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        return config.get("task_concepts", {})
    return {}


def evaluate_context_relatedness(
    input_text: str, expected_type: str, output: str, config_dir: str = "config",
) -> float:
    """评估输出与任务类型的上下文相关度."""
    output_lower = output.lower()
    concepts = _load_task_concepts(config_dir) or _DEFAULT_TASK_CONCEPTS
    type_concepts = concepts.get(expected_type, [])
    if not type_concepts:
        return 0.5
    relevant = sum(1 for c in type_concepts if c in output_lower)
    return min(relevant / max(len(type_concepts), 1), 1.0)
