# 对比实验重新设计：四后端 LLM-as-Judge 评估

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将实验框架重构为 Prepare → Run → Judge 三阶段 Pipeline，支持 LLM-as-Judge 多维评分。

**Architecture:** 三阶段分离：Prepare 加载数据集并预热记忆库；Run 执行测试用例收集原始输出+规则评估；Judge 用独立模型多维评分。每阶段可单独运行/重试，中间结果全部持久化。

**Tech Stack:** Python 3.13, argparse (子命令 CLI), LangChain/LangGraph (工作流), OpenAI 兼容 API (judge), HuggingFace embeddings (本地)

**Spec:** `docs/superpowers/specs/2026-03-29-experiment-redesign-design.md`

---

## File Structure

| 操作 | 文件 | 职责 |
|------|------|------|
| 创建 | `app/experiment/runners/__init__.py` | 包初始化 |
| 创建 | `app/experiment/runners/prepare.py` | Prepare 阶段：数据集加载+划分+预热写入 |
| 创建 | `app/experiment/runners/evaluate.py` | 规则评估函数（从 runner.py 迁移） |
| 创建 | `app/experiment/runners/execute.py` | Run 阶段：执行测试+调用规则评估 |
| 创建 | `app/experiment/runners/judge.py` | Judge 阶段：LLM-as-Judge 多维评分 |
| 修改 | `app/models/settings.py` | 新增 JudgeProviderConfig + get_judge_model() |
| 修改 | `config/llm.json` | 新增 judge 配置节 |
| 重写 | `run_experiment.py` | 子命令式 CLI (prepare/run/judge/all) |
| 删除 | `app/experiment/runner.py` | 旧 ExperimentRunner |
| 删除 | `app/experiment/test_data.py` | 不再需要 |
| 创建 | `tests/test_prepare.py` | Prepare 阶段测试 |
| 创建 | `tests/test_execute.py` | Execute 阶段测试 |
| 创建 | `tests/test_judge.py` | Judge 阶段测试 |

---

## Task 1: 新增 JudgeProviderConfig 到 settings.py

**Files:**
- Modify: `app/models/settings.py`
- Test: `tests/test_settings.py` (已有)

- [ ] **Step 1: 写失败测试**

在 `tests/test_settings.py` 末尾追加：

```python
def test_judge_provider_config_from_dict():
    from app.models.settings import JudgeProviderConfig

    d = {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1", "api_key": "sk-xxx", "temperature": 0.1}
    cfg = JudgeProviderConfig.from_dict(d)
    assert cfg.model == "deepseek-chat"
    assert cfg.base_url == "https://api.deepseek.com/v1"
    assert cfg.api_key == "sk-xxx"
    assert cfg.temperature == 0.1


def test_judge_provider_config_defaults():
    from app.models.settings import JudgeProviderConfig

    cfg = JudgeProviderConfig.from_dict({"model": "test"})
    assert cfg.base_url is None
    assert cfg.api_key is None
    assert cfg.temperature == 0.1


def test_llm_settings_loads_judge(tmp_path, monkeypatch):
    from app.models.settings import LLMSettings
    import json

    config = {
        "llm": [{"model": "qwen", "base_url": "http://localhost:8000/v1"}],
        "judge": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr("app.models.settings.CONFIG_PATH", str(config_file))

    settings = LLMSettings.load()
    assert settings.judge_provider is not None
    assert settings.judge_provider.model == "deepseek-chat"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_settings.py::test_judge_provider_config_from_dict tests/test_settings.py::test_llm_settings_loads_judge -v
```

Expected: FAIL (ImportError / AttributeError)

- [ ] **Step 3: 实现 JudgeProviderConfig**

在 `app/models/settings.py` 的 `EmbeddingProviderConfig` 类之后新增：

```python
@dataclass
class JudgeProviderConfig:
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeProviderConfig":
        return cls(
            model=d["model"],
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
            temperature=d.get("temperature", 0.1),
        )
```

在 `LLMSettings` dataclass 中新增字段：

```python
judge_provider: JudgeProviderConfig | None = None
```

在 `LLMSettings.load()` 的 `return cls(...)` 之前新增：

```python
judge_data = config_data.get("judge")
judge_provider = JudgeProviderConfig.from_dict(judge_data) if judge_data else None

for prefix in ("JUDGE",):
    model = os.getenv(f"{prefix}_MODEL")
    if model:
        judge_provider = JudgeProviderConfig(
            model=model,
            base_url=os.getenv(f"{prefix}_BASE_URL"),
            api_key=os.getenv(f"{prefix}_API_KEY"),
        )
```

修改 `return cls(...)` 增加 `judge_provider=judge_provider` 参数。

在文件末尾新增：

```python
def get_judge_model() -> "ChatModel":
    from app.models.chat import ChatModel

    settings = LLMSettings.load()
    if settings.judge_provider is None:
        raise RuntimeError("No judge model configured. Set JUDGE_MODEL or add 'judge' to config/llm.json")
    cfg = settings.judge_provider
    provider = LLMProviderConfig(
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        temperature=cfg.temperature,
    )
    return ChatModel(providers=[provider], temperature=cfg.temperature)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_settings.py -v
```

Expected: ALL PASS

- [ ] **Step 5: 更新 config/llm.json**

在 `config/llm.json` 的 `"embedding": []` 之后新增：

```json
"judge": {
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "",
  "temperature": 0.1
}
```

- [ ] **Step 6: 提交**

```bash
git add app/models/settings.py config/llm.json tests/test_settings.py
git commit -m "feat: add JudgeProviderConfig to settings"
```

---

## Task 2: 创建 runners 包 + 迁移规则评估函数

**Files:**
- Create: `app/experiment/runners/__init__.py`
- Create: `app/experiment/runners/evaluate.py`
- Test: `tests/test_execute.py`

- [ ] **Step 1: 创建 `app/experiment/runners/__init__.py`**

```python
"""实验 Pipeline 运行器：Prepare → Execute → Judge."""
```

- [ ] **Step 2: 写失败测试**

创建 `tests/test_execute.py`：

```python
"""Tests for the execute runner (evaluation functions migrated from runner.py)."""

from app.experiment.runners.evaluate import (
    evaluate_semantic_accuracy,
    evaluate_context_relatedness,
    infer_intent,
)


def test_infer_intent_schedule_check():
    assert infer_intent("今天有什么安排？") == "schedule_check"


def test_infer_intent_event_add():
    assert infer_intent("提醒我下午三点开会") == "event_add"


def test_infer_intent_event_delete():
    assert infer_intent("取消明天的会议") == "event_delete"


def test_infer_intent_general():
    assert infer_intent("你好") == "general"


def test_semantic_accuracy_positive():
    score = evaluate_semantic_accuracy(
        "提醒我明天开会", "schedule_check", "明天有个会议安排"
    )
    assert score > 0


def test_semantic_accuracy_handles_raw_json():
    raw = '{"reasoning": "用户查询日程", "should_remind": false}'
    score = evaluate_semantic_accuracy("明天有什么安排", "schedule_check", raw)
    assert score > 0


def test_context_relatedness_schedule_check():
    score = evaluate_context_relatedness(
        "明天有什么安排",
        "schedule_check",
        "你的日程安排如下：明天下午三点有个会议提醒",
    )
    assert score > 0
```

- [ ] **Step 3: 运行测试确认失败**

```bash
uv run pytest tests/test_execute.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 4: 创建 `app/experiment/runners/evaluate.py`**

从 `app/experiment/runner.py` 迁移规则评估函数。创建新文件：

```python
"""规则评估函数（从 runner.py 迁移）."""

import json
import os
import re
from typing import Dict, List

INTENT_KEYWORDS: Dict[str, List[str]] = {
    "schedule_check": [
        "时间", "日程", "安排", "查", "看", "几点", "什么时候", "明天", "今天", "后天", "这周", "下周",
        "schedule", "when", "time", "what", "check", "look", "see", "tomorrow", "today", "calendar", "appointment",
    ],
    "event_add": [
        "添加", "新建", "提醒", "记录", "创建", "加", "设定", "下午", "早上", "晚上", "点", "分钟", "小时",
        "add", "new", "remind", "create", "set", "schedule", "pm", "am", "minute", "hour",
    ],
    "event_delete": [
        "删除", "取消", "去掉", "移除", "不要",
        "delete", "cancel", "remove", "don't",
    ],
    "general": [],
}

NEGATIVE_PATTERNS = ["不要", "别", "取消", "去掉", "删除", "移除", "don't", "dont", "cancel", "remove", "delete", "stop", "no"]


def infer_intent(query: str) -> str:
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


def evaluate_semantic_accuracy(input_text: str, expected_type: str, output: str) -> float:
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


def _load_task_concepts(config_dir: str = "config") -> Dict[str, List[str]]:
    config_path = os.path.join(config_dir, "evaluation_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("task_concepts", {})
    return {}


_DEFAULT_TASK_CONCEPTS: Dict[str, List[str]] = {
    "schedule_check": ["时间", "日程", "安排", "查询", "提醒", "会议", "几点", "什么"],
    "event_add": ["添加", "创建", "提醒", "设置", "安排", "记录", "新建", "会议", "点"],
    "event_delete": ["取消", "删除", "移除", "去掉", "不要", "no", "cancel"],
    "general": ["好", "天气", "最近", "怎么样", "hello", "how", "今天"],
}


def evaluate_context_relatedness(input_text: str, expected_type: str, output: str, config_dir: str = "config") -> float:
    output_lower = output.lower()
    concepts = _load_task_concepts(config_dir) or _DEFAULT_TASK_CONCEPTS
    type_concepts = concepts.get(expected_type, [])
    if not type_concepts:
        return 0.5
    relevant = sum(1 for c in type_concepts if c in output_lower)
    return min(relevant / max(len(type_concepts), 1), 1.0)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/test_execute.py -v
```

Expected: ALL PASS

- [ ] **Step 6: 提交**

```bash
git add app/experiment/runners/__init__.py app/experiment/runners/evaluate.py tests/test_execute.py
git commit -m "feat: add evaluate module with migrated rule-based evaluation functions"
```

---

## Task 3: 实现 Prepare 阶段

**Files:**
- Create: `app/experiment/runners/prepare.py`
- Test: `tests/test_prepare.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_prepare.py`：

```python
"""Tests for the prepare runner."""

import json
import os
from unittest.mock import MagicMock, patch

from app.experiment.runners.prepare import PrepareRunner


def _mock_dataset(name):
    if name == "sgd_calendar":
        return [
            {"input": f"sgd input {i}", "type": "event_add"}
            for i in range(20)
        ]
    elif name == "scheduler":
        return [
            {"input": f"sched input {i}", "type": "schedule_check"}
            for i in range(20)
        ]
    raise ValueError(f"Unknown dataset: {name}")


def test_prepare_creates_directory_structure(tmp_path):
    with patch("app.experiment.runners.prepare._load_dataset", side_effect=_mock_dataset), \
         patch("app.experiment.runners.prepare.get_chat_model") as mock_chat_cls:
        mock_chat = MagicMock()
        mock_chat.generate.return_value = "已确认"
        mock_chat_cls.return_value = mock_chat

        runner = PrepareRunner(output_dir=str(tmp_path / "exp"), config_dir="config")
        result = runner.prepare(datasets=["sgd_calendar"], test_count=5, warmup_ratio=0.7, seed=42)

        run_id = result["run_id"]
        base = tmp_path / "exp" / run_id
        assert (base / "prepared.json").exists()
        assert (base / "warmup" / "sgd_calendar.json").exists()
        for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
            assert (base / "stores" / method).is_dir()


def test_prepare_splits_correctly(tmp_path):
    with patch("app.experiment.runners.prepare._load_dataset", side_effect=_mock_dataset), \
         patch("app.experiment.runners.prepare.get_chat_model") as mock_chat_cls:
        mock_chat = MagicMock()
        mock_chat.generate.return_value = "已确认"
        mock_chat_cls.return_value = mock_chat

        runner = PrepareRunner(output_dir=str(tmp_path / "exp"), config_dir="config")
        result = runner.prepare(datasets=["sgd_calendar"], test_count=5, warmup_ratio=0.7, seed=42)

        run_id = result["run_id"]
        with open(tmp_path / "exp" / run_id / "prepared.json", encoding="utf-8") as f:
            data = json.load(f)

        total_cases = len(data["test_cases"])
        sgd_info = data["datasets"]["sgd_calendar"]
        assert total_cases == sgd_info["test_count"]
        assert sgd_info["warmup_count"] + sgd_info["test_count"] > 0


def test_prepare_reproducible(tmp_path):
    with patch("app.experiment.runners.prepare._load_dataset", side_effect=_mock_dataset), \
         patch("app.experiment.runners.prepare.get_chat_model") as mock_chat_cls:
        mock_chat = MagicMock()
        mock_chat.generate.return_value = "已确认"
        mock_chat_cls.return_value = mock_chat

        runner = PrepareRunner(output_dir=str(tmp_path / "exp"), config_dir="config")
        result_a = runner.prepare(datasets=["sgd_calendar"], test_count=5, warmup_ratio=0.7, seed=42)
        result_b = runner.prepare(datasets=["sgd_calendar"], test_count=5, warmup_ratio=0.7, seed=42)

        inputs_a = [c["input"] for c in result_a["test_cases"]]
        inputs_b = [c["input"] for c in result_b["test_cases"]]
        assert inputs_a == inputs_b


def test_prepare_warmup_file_format(tmp_path):
    with patch("app.experiment.runners.prepare._load_dataset", side_effect=_mock_dataset), \
         patch("app.experiment.runners.prepare.get_chat_model") as mock_chat_cls:
        mock_chat = MagicMock()
        mock_chat.generate.return_value = "已确认"
        mock_chat_cls.return_value = mock_chat

        runner = PrepareRunner(output_dir=str(tmp_path / "exp"), config_dir="config")
        result = runner.prepare(datasets=["sgd_calendar"], test_count=5, warmup_ratio=0.7, seed=42)

        run_id = result["run_id"]
        with open(tmp_path / "exp" / run_id / "warmup" / "sgd_calendar.json", encoding="utf-8") as f:
            warmup = json.load(f)

        assert isinstance(warmup, list)
        if warmup:
            assert "id" in warmup[0]
            assert "input" in warmup[0]
            assert "type" in warmup[0]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_prepare.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 PrepareRunner**

创建 `app/experiment/runners/prepare.py`：

```python
"""Prepare 阶段：加载数据集、划分预热/测试集、写入记忆库."""

import json
import logging
import os
import random
import shutil
from datetime import datetime
from typing import List, Dict

from app.memory.types import MemoryMode

logger = logging.getLogger(__name__)

_DATASET_LOADERS = {
    "sgd_calendar": "app.experiment.loaders.sgd_calendar",
    "scheduler": "app.experiment.loaders.scheduler",
}


def _load_dataset(name: str) -> List[Dict]:
    if name == "sgd_calendar":
        from app.experiment.loaders.sgd_calendar import get_sgd_calendar_test_cases
        return get_sgd_calendar_test_cases()
    elif name == "scheduler":
        from app.experiment.loaders.scheduler import get_scheduler_test_cases
        return get_scheduler_test_cases()
    raise ValueError(f"Unknown dataset: {name}")


class PrepareRunner:
    def __init__(self, output_dir: str, config_dir: str = "config"):
        self.output_dir = output_dir
        self.config_dir = config_dir

    def prepare(
        self,
        datasets: List[str],
        test_count: int = 50,
        warmup_ratio: float = 0.7,
        seed: int = 42,
    ) -> Dict:
        random.seed(seed)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.join(self.output_dir, run_id)
        os.makedirs(base_dir, exist_ok=True)

        all_test_cases: List[Dict] = []
        dataset_stats: Dict[str, Dict] = {}
        warmup_data: Dict[str, List[Dict]] = {}

        for ds_name in datasets:
            raw_cases = _load_dataset(ds_name)
            random.shuffle(raw_cases)

            split_idx = int(len(raw_cases) * warmup_ratio)
            warmup_cases = raw_cases[:split_idx]
            test_cases = raw_cases[split_idx:split_idx + test_count]

            dataset_stats[ds_name] = {
                "warmup_count": len(warmup_cases),
                "test_count": len(test_cases),
            }

            for i, tc in enumerate(test_cases):
                all_test_cases.append({
                    "id": f"{ds_name}_{i}",
                    "input": tc["input"],
                    "type": tc.get("type", "general"),
                    "dataset": ds_name,
                })

            warmup_data[ds_name] = [
                {"id": f"{ds_name}_w{i}", "input": tc["input"], "type": tc.get("type", "general"), "response": ""}
                for i, tc in enumerate(warmup_cases)
            ]

        prepared = {
            "run_id": run_id,
            "seed": seed,
            "warmup_ratio": warmup_ratio,
            "datasets": dataset_stats,
            "test_cases": all_test_cases,
            "warmup_files": {},
        }

        warmup_dir = os.path.join(base_dir, "warmup")
        os.makedirs(warmup_dir, exist_ok=True)
        for ds_name, data in warmup_data.items():
            warmup_file = os.path.join(warmup_dir, f"{ds_name}.json")
            with open(warmup_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            prepared["warmup_files"][ds_name] = f"warmup/{ds_name}.json"

        with open(os.path.join(base_dir, "prepared.json"), "w", encoding="utf-8") as f:
            json.dump(prepared, f, ensure_ascii=False, indent=2)

        self._warmup_stores(base_dir, warmup_data)

        return prepared

    def _warmup_stores(self, base_dir: str, warmup_data: Dict[str, List[Dict]]) -> None:
        from app.memory.memory import MemoryModule
        from app.models.settings import get_chat_model

        chat_model = get_chat_model()

        all_warmup: List[Dict] = []
        for ds_name, cases in warmup_data.items():
            all_warmup.extend(cases)

        for mode in MemoryMode:
            store_dir = os.path.join(base_dir, "stores", mode.value)
            os.makedirs(store_dir, exist_ok=True)
            self._init_store_files(store_dir)

            mm = MemoryModule(data_dir=store_dir, chat_model=chat_model)
            mm.set_default_mode(mode)

            for item in all_warmup:
                response = chat_model.generate(
                    f"你是一个车载日程助手。用户说了以下内容，请用一句话简短回复确认：\n\n{item['input']}"
                )
                mm.write_interaction(item["input"], response)

            logger.info(f"Warmed up {mode.value} with {len(all_warmup)} items")

    def _init_store_files(self, store_dir: str) -> None:
        defaults = {
            "events.json": [],
            "strategies.json": {},
            "interactions.json": [],
            "memorybank_summaries.json": {"daily_summaries": {}, "overall_summary": ""},
            "feedback.json": [],
        }
        for fname, data in defaults.items():
            fpath = os.path.join(store_dir, fname)
            if not os.path.exists(fpath):
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: 运行测试确认通过**

注意：`test_prepare_warmup_file_format` 和 `test_prepare_splits_correctly` 需要 HuggingFace 数据集下载，可能在无网络环境失败。如果数据集可用：

```bash
uv run pytest tests/test_prepare.py -v
```

Expected: ALL PASS (如网络不可用，标记为 skip)

- [ ] **Step 5: 提交**

```bash
git add app/experiment/runners/prepare.py tests/test_prepare.py
git commit -m "feat: add PrepareRunner for experiment pipeline stage 1"
```

---

## Task 4: 实现 Execute 阶段

**Files:**
- Create: `app/experiment/runners/execute.py`
- Modify: `tests/test_execute.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_execute.py` 末尾追加：

```python
import json
import os
from unittest.mock import MagicMock, patch

from app.experiment.runners.execute import ExecuteRunner


def test_execute_creates_raw_results(tmp_path):
    prepared_dir = tmp_path / "exp" / "run1"
    prepared_dir.mkdir(parents=True)
    prepared = {
        "run_id": "run1",
        "test_cases": [
            {"id": "test_0", "input": "提醒我开会", "type": "event_add", "dataset": "test"},
        ],
    }
    with open(prepared_dir / "prepared.json", "w", encoding="utf-8") as f:
        json.dump(prepared, f, ensure_ascii=False)

    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        store_dir = prepared_dir / "stores" / method
        store_dir.mkdir(parents=True)

    runner = ExecuteRunner(prepared_dir=str(prepared_dir), config_dir="config")

    with patch("app.experiment.runners.execute.create_workflow") as mock_create:
        mock_wf = MagicMock()
        mock_wf.run.return_value = ("提醒已发送: 开会", "evt_001")
        mock_create.return_value = mock_wf

        runner.execute()

    results_dir = prepared_dir / "results"
    assert results_dir.exists()
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        result_file = results_dir / f"{method}_raw.json"
        assert result_file.exists()
        with open(result_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["method"] == method
        assert len(data["cases"]) == 1
        assert data["cases"][0]["id"] == "test_0"
        assert data["cases"][0]["task_completed"] is True


def test_execute_handles_failure(tmp_path):
    prepared_dir = tmp_path / "exp" / "run2"
    prepared_dir.mkdir(parents=True)
    prepared = {
        "run_id": "run2",
        "test_cases": [
            {"id": "test_0", "input": "测试", "type": "general", "dataset": "test"},
        ],
    }
    with open(prepared_dir / "prepared.json", "w", encoding="utf-8") as f:
        json.dump(prepared, f, ensure_ascii=False)

    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        store_dir = prepared_dir / "stores" / method
        store_dir.mkdir(parents=True)

    runner = ExecuteRunner(prepared_dir=str(prepared_dir), config_dir="config")

    with patch("app.experiment.runners.execute.create_workflow") as mock_create:
        mock_wf = MagicMock()
        mock_wf.run.side_effect = RuntimeError("LLM failed")
        mock_create.return_value = mock_wf

        runner.execute()

    with open(prepared_dir / "results" / "keyword_raw.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["cases"][0]["task_completed"] is False
    assert data["cases"][0]["error"] == "RuntimeError: LLM failed"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_execute.py::test_execute_creates_raw_results tests/test_execute.py::test_execute_handles_failure -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 ExecuteRunner**

创建 `app/experiment/runners/execute.py`：

```python
"""Execute 阶段：对每个后端执行测试用例，收集原始输出 + 规则评估."""

import json
import logging
import os
import time
from typing import Dict, List, Optional

from app.experiment.runners.evaluate import (
    evaluate_context_relatedness,
    evaluate_semantic_accuracy,
)
from app.memory.types import MemoryMode
from app.agents.workflow import create_workflow
from app.storage.json_store import JSONStore

logger = logging.getLogger(__name__)


class ExecuteRunner:
    def __init__(self, prepared_dir: str, config_dir: str = "config"):
        self.prepared_dir = prepared_dir
        self.config_dir = config_dir

    def execute(self) -> Dict[str, Dict]:
        with open(os.path.join(self.prepared_dir, "prepared.json"), "r", encoding="utf-8") as f:
            prepared = json.load(f)

        test_cases = prepared["test_cases"]
        run_id = prepared["run_id"]
        results_dir = os.path.join(self.prepared_dir, "results")
        os.makedirs(results_dir, exist_ok=True)

        all_results: Dict[str, Dict] = {}

        for mode in MemoryMode:
            store_dir = os.path.join(self.prepared_dir, "stores", mode.value)
            method_result = self._run_method(mode.value, test_cases, store_dir)
            method_result["run_id"] = run_id
            method_result["method"] = mode.value

            output_path = os.path.join(results_dir, f"{mode.value}_raw.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(method_result, f, ensure_ascii=False, indent=2)

            all_results[mode.value] = method_result

        return all_results

    def _run_method(self, method: str, test_cases: List[Dict], store_dir: str) -> Dict:
        cases_result = []

        for case in test_cases:
            try:
                workflow = create_workflow(data_dir=store_dir, memory_mode=method)
                start = time.time()
                result, event_id = workflow.run(case["input"])
                elapsed_ms = (time.time() - start) * 1000

                raw_output = self._extract_output(result, store_dir)
                task_completed = True
                accuracy = evaluate_semantic_accuracy(case["input"], case["type"], raw_output)
                relatedness = evaluate_context_relatedness(case["input"], case["type"], raw_output, self.config_dir)
                error = None
            except Exception as e:
                logger.warning(f"Execute failed for case '{case['id']}': {e}")
                elapsed_ms = 0
                result = ""
                raw_output = ""
                event_id = ""
                task_completed = False
                accuracy = 0.0
                relatedness = 0.0
                error = f"{type(e).__name__}: {e}"

            cases_result.append({
                "id": case["id"],
                "input": case["input"],
                "type": case["type"],
                "output": result[:500] if result else "",
                "raw_output": raw_output[:500] if raw_output else "",
                "event_id": event_id or "",
                "latency_ms": round(elapsed_ms, 1),
                "task_completed": task_completed,
                "semantic_accuracy": round(accuracy, 4),
                "context_relatedness": round(relatedness, 4),
                "error": error,
            })

            status = "OK" if task_completed else "FAIL"
            logger.info(f"[{method}] {case['id']} {status} ({elapsed_ms:.0f}ms)")

        return {"cases": cases_result}

    def _extract_output(self, result: str, data_dir: str) -> str:
        events_store = JSONStore(data_dir, "events.json", list)
        events = events_store.read()
        if events:
            last_event = events[-1]
            decision = last_event.get("decision", {})
            if isinstance(decision, str):
                return decision
            content = (
                decision.get("reminder_content")
                or decision.get("remind_content")
                or decision.get("content")
            )
            if content:
                return content
            for key in ("reasoning", "raw"):
                val = decision.get(key, "")
                if val:
                    return val
        return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_execute.py -v
```

Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add app/experiment/runners/execute.py tests/test_execute.py
git commit -m "feat: add ExecuteRunner for experiment pipeline stage 2"
```

---

## Task 5: 实现 Judge 阶段

**Files:**
- Create: `app/experiment/runners/judge.py`
- Create: `tests/test_judge.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_judge.py`：

```python
"""Tests for the judge runner."""

import json
import os
from unittest.mock import MagicMock, patch

from app.experiment.runners.judge import JudgeRunner


def _setup_prepared_dir(tmp_path, run_id="test_run"):
    prepared_dir = tmp_path / "exp" / run_id
    results_dir = prepared_dir / "results"
    judged_dir = prepared_dir / "judged"
    results_dir.mkdir(parents=True)

    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        raw = {
            "run_id": run_id,
            "method": method,
            "cases": [
                {
                    "id": "test_0",
                    "input": "提醒我开会",
                    "type": "event_add",
                    "output": "提醒已发送: 会议提醒",
                    "raw_output": "会议提醒",
                    "event_id": "evt_001",
                    "latency_ms": 1000,
                    "task_completed": True,
                    "semantic_accuracy": 0.8,
                    "context_relatedness": 0.6,
                    "error": None,
                }
            ],
        }
        with open(results_dir / f"{method}_raw.json", "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    return prepared_dir


def test_judge_creates_judged_files(tmp_path):
    prepared_dir = _setup_prepared_dir(tmp_path)

    mock_judge = MagicMock()
    mock_judge.generate.return_value = json.dumps({
        "memory_recall": {"score": 4, "reason": "good"},
        "relevance": {"score": 5, "reason": "good"},
        "task_quality": {"score": 4, "reason": "good"},
        "coherence": {"score": 4, "reason": "good"},
        "helpfulness": {"score": 4, "reason": "good"},
    })

    with patch("app.experiment.runners.judge.get_judge_model", return_value=mock_judge):
        runner = JudgeRunner(prepared_dir=str(prepared_dir))
        runner.judge()

    judged_dir = prepared_dir / "judged"
    assert (judged_dir / "final_report.json").exists()
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        assert (judged_dir / f"{method}_judged.json").exists()

    with open(judged_dir / "final_report.json", encoding="utf-8") as f:
        report = json.load(f)
    assert "summary" in report
    assert "keyword" in report["summary"]
    assert report["summary"]["keyword"]["case_count"] == 1


def test_judge_handles_parse_error(tmp_path):
    prepared_dir = _setup_prepared_dir(tmp_path)

    mock_judge = MagicMock()
    mock_judge.generate.return_value = "this is not json"

    with patch("app.experiment.runners.judge.get_judge_model", return_value=mock_judge):
        runner = JudgeRunner(prepared_dir=str(prepared_dir))
        runner.judge()

    judged_dir = prepared_dir / "judged"
    with open(judged_dir / "keyword_judged.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["cases"][0].get("judge_error") is not None


def test_judge_skips_already_judged(tmp_path):
    prepared_dir = _setup_prepared_dir(tmp_path)
    judged_dir = prepared_dir / "judged"
    judged_dir.mkdir(exist_ok=True)

    existing = {
        "run_id": "test_run",
        "method": "keyword",
        "cases": [{"id": "test_0", "scores": {"memory_recall": {"score": 3, "reason": "ok"}}, "weighted_total": 3.0}],
    }
    with open(judged_dir / "keyword_judged.json", "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    mock_judge = MagicMock()

    with patch("app.experiment.runners.judge.get_judge_model", return_value=mock_judge):
        runner = JudgeRunner(prepared_dir=str(prepared_dir))
        runner.judge()

    mock_judge.generate.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_judge.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 JudgeRunner**

创建 `app/experiment/runners/judge.py`：

```python
"""Judge 阶段：LLM-as-Judge 多维评分."""

import json
import logging
import os
import re
from typing import Dict, List, Optional

from app.memory.types import MemoryMode

logger = logging.getLogger(__name__)

JUDGE_WEIGHTS = {
    "memory_recall": 0.25,
    "relevance": 0.25,
    "task_quality": 0.20,
    "coherence": 0.15,
    "helpfulness": 0.15,
}

JUDGE_PROMPT_TEMPLATE = """你是一个车载AI智能体的质量评估专家。请评估以下系统回复的质量。

## 用户输入
{input}

## 系统回复
{output}

## 任务类型
{task_type}

## 评估维度
请对以下每个维度打分（1-5分），并简要说明理由：

1. **记忆召回 (memory_recall)**: 系统是否正确利用了历史记忆/上下文信息？(1=完全未利用, 5=完美利用)
2. **响应相关性 (relevance)**: 回复是否与用户意图紧密相关？(1=完全无关, 5=高度相关)
3. **任务完成质量 (task_quality)**: 日程管理任务是否被正确处理？(1=完全错误, 5=完美完成)
4. **上下文一致性 (coherence)**: 回复在驾驶场景下是否合理连贯？(1=完全不连贯, 5=非常连贯)
5. **整体有用性 (helpfulness)**: 对驾驶员的实际帮助程度？(1=无帮助, 5=非常有帮助)

请以JSON格式输出评分结果：
{{"memory_recall": {{"score": N, "reason": "..."}},"relevance": {{"score": N, "reason": "..."}},"task_quality": {{"score": N, "reason": "..."}},"coherence": {{"score": N, "reason": "..."}},"helpfulness": {{"score": N, "reason": "..."}}}}"""


def _parse_judge_response(response: str) -> Optional[Dict]:
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", response.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "memory_recall" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\"memory_recall\"[\s\S]*\}", response)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _compute_weighted_total(scores: Dict) -> float:
    total = 0.0
    for dim, weight in JUDGE_WEIGHTS.items():
        dim_data = scores.get(dim, {})
        score = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
        total += score * weight
    return round(total, 2)


class JudgeRunner:
    def __init__(self, prepared_dir: str):
        self.prepared_dir = prepared_dir

    def judge(self) -> Dict:
        from app.models.settings import get_judge_model

        judge_model = get_judge_model()
        judged_dir = os.path.join(self.prepared_dir, "judged")
        os.makedirs(judged_dir, exist_ok=True)

        results_dir = os.path.join(self.prepared_dir, "results")
        summary: Dict[str, Dict] = {}

        for mode in MemoryMode:
            raw_path = os.path.join(results_dir, f"{mode.value}_raw.json")
            if not os.path.exists(raw_path):
                logger.warning(f"No results for {mode.value}, skipping")
                continue

            with open(raw_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            judged_cases = self._judge_method(judge_model, mode.value, raw_data["cases"], judged_dir)

            method_scores = self._compute_method_summary(judged_cases, raw_data["cases"])
            method_scores["case_count"] = len(judged_cases)
            summary[mode.value] = method_scores

        final_report = {
            "run_id": raw_data.get("run_id", ""),
            "judge_model": judge_model.providers[0].model if judge_model.providers else "unknown",
            "summary": summary,
        }

        with open(os.path.join(judged_dir, "final_report.json"), "w", encoding="utf-8") as f:
            json.dump(final_report, f, ensure_ascii=False, indent=2)

        return final_report

    def _judge_method(self, judge_model, method: str, cases: List[Dict], judged_dir: str) -> List[Dict]:
        judged_path = os.path.join(judged_dir, f"{method}_judged.json")

        already_judged = {}
        if os.path.exists(judged_path):
            with open(judged_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            for c in existing.get("cases", []):
                if "judge_error" not in c:
                    already_judged[c["id"]] = c

        judged_cases = []
        for case in cases:
            if case["id"] in already_judged:
                judged_cases.append(already_judged[case["id"]])
                continue

            prompt = JUDGE_PROMPT_TEMPLATE.format(
                input=case["input"],
                output=case.get("output", ""),
                task_type=case.get("type", "general"),
            )

            try:
                response = judge_model.generate(prompt)
                scores = _parse_judge_response(response)
                if scores is None:
                    raise ValueError("Failed to parse judge response")
                weighted_total = _compute_weighted_total(scores)
                judged_case = {
                    "id": case["id"],
                    "scores": scores,
                    "weighted_total": weighted_total,
                }
            except Exception as e:
                logger.warning(f"Judge failed for {case['id']}: {e}")
                judged_case = {
                    "id": case["id"],
                    "scores": {},
                    "weighted_total": 0.0,
                    "judge_error": str(e),
                }

            judged_cases.append(judged_case)
            logger.info(f"[judged] {case['id']} → {judged_case.get('weighted_total', 0):.2f}")

        judged_output = {
            "run_id": cases[0].get("run_id", "") if cases else "",
            "method": method,
            "cases": judged_cases,
        }

        with open(judged_path, "w", encoding="utf-8") as f:
            json.dump(judged_output, f, ensure_ascii=False, indent=2)

        return judged_cases

    def _compute_method_summary(self, judged_cases: List[Dict], raw_cases: List[Dict]) -> Dict:
        if not judged_cases:
            return {}

        totals = {dim: 0.0 for dim in JUDGE_WEIGHTS}
        weighted_totals = []
        latencies = []
        completions = 0
        valid = 0

        for jc in judged_cases:
            if "judge_error" in jc:
                continue
            valid += 1
            wt = jc.get("weighted_total", 0)
            weighted_totals.append(wt)
            for dim in JUDGE_WEIGHTS:
                dim_data = jc.get("scores", {}).get(dim, {})
                score = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                totals[dim] += score

        for rc in raw_cases:
            if rc.get("latency_ms"):
                latencies.append(rc["latency_ms"])
            if rc.get("task_completed"):
                completions += 1

        result = {}
        if valid > 0:
            result["avg_weighted_total"] = round(sum(weighted_totals) / valid, 2)
            for dim in JUDGE_WEIGHTS:
                result[f"avg_{dim}"] = round(totals[dim] / valid, 2)
        if latencies:
            result["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1)
        result["task_completion_rate"] = round(completions / len(raw_cases), 4) if raw_cases else 0

        return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_judge.py -v
```

Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add app/experiment/runners/judge.py tests/test_judge.py
git commit -m "feat: add JudgeRunner for experiment pipeline stage 3"
```

---

## Task 6: 重写 run_experiment.py CLI

**Files:**
- Rewrite: `run_experiment.py`

- [ ] **Step 1: 重写 CLI**

将 `run_experiment.py` 重写为子命令式 CLI：

```python
#!/usr/bin/env python3
"""实验 Pipeline CLI：prepare → run → judge."""

import argparse
import sys

from app.experiment.runners.prepare import PrepareRunner
from app.experiment.runners.execute import ExecuteRunner
from app.experiment.runners.judge import JudgeRunner


def cmd_prepare(args):
    runner = PrepareRunner(output_dir=args.output_dir, config_dir=args.config_dir)
    result = runner.prepare(
        datasets=args.datasets,
        test_count=args.test_count,
        warmup_ratio=args.warmup_ratio,
        seed=args.seed,
    )
    print(f"Prepare done. Run ID: {result['run_id']}")
    print(f"Test cases: {sum(d['test_count'] for d in result['datasets'].values())}")
    print(f"Warmup: {sum(d['warmup_count'] for d in result['datasets'].values())}")
    return result


def cmd_run(args):
    prepared_dir = args.prepared_dir
    runner = ExecuteRunner(prepared_dir=prepared_dir, config_dir=args.config_dir)
    result = runner.execute()
    total = sum(len(r.get("cases", [])) for r in result.values())
    print(f"Run done. {total} cases across {len(result)} methods.")
    return result


def cmd_judge(args):
    prepared_dir = args.prepared_dir
    runner = JudgeRunner(prepared_dir=prepared_dir)
    report = runner.judge()

    print("\n" + "=" * 80)
    print("JUDGE REPORT")
    print("=" * 80)
    for method, metrics in report.get("summary", {}).items():
        wt = metrics.get("avg_weighted_total", 0)
        lat = metrics.get("avg_latency_ms", 0)
        comp = metrics.get("task_completion_rate", 0)
        print(f"  {method:<12} weighted={wt:.2f}  latency={lat:.0f}ms  completion={comp:.1%}")

    return report


def cmd_all(args):
    prep_result = cmd_prepare(args)
    prepared_dir = f"{args.output_dir}/{prep_result['run_id']}"

    run_args = argparse.Namespace(prepared_dir=prepared_dir, config_dir=args.config_dir)
    cmd_run(run_args)

    judge_args = argparse.Namespace(prepared_dir=prepared_dir)
    cmd_judge(judge_args)


def main():
    parser = argparse.ArgumentParser(description="Experiment Pipeline: prepare → run → judge")
    parser.add_argument("--config-dir", default="config", help="Config directory")

    sub = parser.add_subparsers(dest="command", required=True)

    # prepare
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--datasets", nargs="+", default=["sgd_calendar", "scheduler"])
    p_prep.add_argument("--test-count", type=int, default=50)
    p_prep.add_argument("--warmup-ratio", type=float, default=0.7)
    p_prep.add_argument("--seed", type=int, default=42)
    p_prep.add_argument("--output-dir", default="data/exp")

    # run
    p_run = sub.add_parser("run")
    p_run.add_argument("prepared_dir", help="Path to prepared experiment directory")
    p_run.add_argument("--config-dir", default="config")

    # judge
    p_judge = sub.add_parser("judge")
    p_judge.add_argument("prepared_dir", help="Path to prepared experiment directory")

    # all
    p_all = sub.add_parser("all")
    p_all.add_argument("--datasets", nargs="+", default=["sgd_calendar", "scheduler"])
    p_all.add_argument("--test-count", type=int, default=50)
    p_all.add_argument("--warmup-ratio", type=float, default=0.7)
    p_all.add_argument("--seed", type=int, default=42)
    p_all.add_argument("--output-dir", default="data/exp")

    args = parser.parse_args()

    handlers = {
        "prepare": cmd_prepare,
        "run": cmd_run,
        "judge": cmd_judge,
        "all": cmd_all,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 CLI 帮助**

```bash
uv run python run_experiment.py --help
uv run python run_experiment.py prepare --help
uv run python run_experiment.py run --help
uv run python run_experiment.py judge --help
uv run python run_experiment.py all --help
```

Expected: 各子命令帮助信息正常显示

- [ ] **Step 3: 提交**

```bash
git add run_experiment.py
git commit -m "feat: rewrite CLI as subcommand-based pipeline (prepare/run/judge/all)"
```

---

## Task 7: 删除旧文件 + 更新测试

**Files:**
- Delete: `app/experiment/runner.py`
- Delete: `app/experiment/test_data.py`
- Modify: `tests/test_experiment_runner.py` → 迁移到新测试或删除

- [ ] **Step 1: 更新旧测试引用**

检查 `tests/test_experiment_runner.py` 中的测试是否已被新测试覆盖：

- `test_seed_reproducibility` / `test_seed_produces_different_without_seed` → 引用 `DataGenerator`（将被删除），这些测试已不再需要（Prepare 阶段有自己的可复现性测试）
- `test_raw_preserved_in_context_node` / `test_raw_preserved_in_strategy_node` → 测试 workflow 节点，不依赖 runner.py，应保留但需移到合适位置
- `test_split_words_uses_bigrams` / `test_semantic_accuracy_with_raw_output` / `test_context_relatedness_schedule_check` → 已迁移到 `test_execute.py`
- `test_run_method_uses_isolated_data_dir` → 已在 `test_execute.py::test_execute_creates_raw_results` 覆盖

将 workflow 相关测试保留在 `test_experiment_runner.py` 但改为不引用已删除模块：

```python
"""Tests for workflow node output preservation (migrated from old experiment runner tests)."""

from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage
from app.agents.state import AgentState
from app.agents.workflow import AgentWorkflow


def test_raw_preserved_in_context_node():
    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"time": "10:00", "location": "home"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory_module = MagicMock()
    workflow.memory_module.search.return_value = []
    workflow.memory_module.get_history.return_value = []
    workflow.memory_module.chat_model = mock_chat

    state: AgentState = {
        "messages": [HumanMessage(content="现在几点")],
        "context": {},
        "task": {},
        "decision": {},
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert result["context"].get("raw") is not None


def test_raw_preserved_in_strategy_node():
    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"should_remind": false, "reasoning": "test"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory_module = MagicMock()
    workflow.memory_module.chat_model = mock_chat

    state: AgentState = {
        "messages": [HumanMessage(content="test")],
        "context": {},
        "task": {},
        "decision": {},
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    with patch("app.agents.workflow.JSONStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.read.return_value = {"reminder_weights": {"default": 1.0}}
        mock_store_cls.return_value = mock_store

        result = workflow._strategy_node(state)
        assert result["decision"].get("raw") is not None
```

- [ ] **Step 2: 删除旧文件**

```bash
rm app/experiment/runner.py
rm app/experiment/test_data.py
```

- [ ] **Step 3: 运行全部测试确认无回归**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 4: Lint 检查**

```bash
uv run ruff check app/experiment/runners/ run_experiment.py tests/test_prepare.py tests/test_execute.py tests/test_judge.py
```

Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: remove old runner.py and test_data.py, migrate tests"
```

---

## Task 8: 集成测试

**Files:**
- Modify: `tests/test_prepare.py`
- Modify: `tests/test_execute.py`
- Modify: `tests/test_judge.py`

- [ ] **Step 1: 添加端到端冒烟测试**

在 `tests/test_judge.py` 末尾追加：

```python
def test_e2e_pipeline(tmp_path):
    """End-to-end smoke test: prepare (mock LLM) → execute (mock workflow) → judge (mock judge)."""
    from app.experiment.runners.prepare import PrepareRunner
    from app.experiment.runners.execute import ExecuteRunner
    from app.experiment.runners.judge import JudgeRunner

    prepared_dir = tmp_path / "exp" / "e2e"
    prepared_dir.mkdir(parents=True)

    # Manually create a minimal prepared.json instead of calling prepare
    # (which requires dataset download + LLM)
    test_cases = [
        {"id": "test_0", "input": "提醒我开会", "type": "event_add", "dataset": "test"},
        {"id": "test_1", "input": "今天有什么安排", "type": "schedule_check", "dataset": "test"},
    ]

    import json
    prepared = {
        "run_id": "e2e",
        "test_cases": test_cases,
    }
    with open(prepared_dir / "prepared.json", "w", encoding="utf-8") as f:
        json.dump(prepared, f, ensure_ascii=False)

    from app.memory.types import MemoryMode
    for mode in MemoryMode:
        store_dir = prepared_dir / "stores" / mode.value
        store_dir.mkdir(parents=True)

    # Execute with mock
    with patch("app.experiment.runners.execute.create_workflow") as mock_create:
        mock_wf = MagicMock()
        mock_wf.run.return_value = ("提醒已发送: 会议提醒", "evt_001")
        mock_create.return_value = mock_wf

        exec_runner = ExecuteRunner(prepared_dir=str(prepared_dir), config_dir="config")
        exec_runner.execute()

    # Judge with mock
    mock_judge = MagicMock()
    mock_judge.generate.return_value = json.dumps({
        "memory_recall": {"score": 4, "reason": "ok"},
        "relevance": {"score": 4, "reason": "ok"},
        "task_quality": {"score": 4, "reason": "ok"},
        "coherence": {"score": 4, "reason": "ok"},
        "helpfulness": {"score": 4, "reason": "ok"},
    })
    mock_judge.providers = [MagicMock(model="mock-judge")]

    with patch("app.experiment.runners.judge.get_judge_model", return_value=mock_judge):
        judge_runner = JudgeRunner(prepared_dir=str(prepared_dir))
        report = judge_runner.judge()

    assert "summary" in report
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        assert method in report["summary"]
        assert report["summary"][method]["case_count"] == 2
        assert report["summary"][method]["avg_weighted_total"] > 0
```

- [ ] **Step 2: 运行全部测试**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 3: 最终 lint**

```bash
uv run ruff check app/ tests/ run_experiment.py
```

Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add tests/
git commit -m "test: add e2e pipeline smoke test"
```

---

## 尚未解决的问题

- **预热 LLM 成本**：Prepare 阶段需要为每条预热数据调用 LLM 生成 response（~70条 × 4后端），但同一 input 的 response 可复用，实际只需 ~70 次 LLM 调用。
- **数据集可用性**：SGD-Calendar 和 Scheduler 数据集需要从 HuggingFace 下载，网络不可用时 Prepare 阶段会失败。可考虑本地缓存。
