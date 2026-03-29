# VehicleMemBench 集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 VehicleMemBench 替换现有实验系统，评测自研 4 种记忆后端。

**Architecture:** VehicleMemBench 作为 git submodule 引入（禁止修改），adapters/ 层桥接自研记忆后端，runner.py 自写评测管线直接调用 VehicleMemBench 底层函数。

**Tech Stack:** Python 3.13, openai, langchain, pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-03-30-vehiclemembench-integration-design.md`

---

## File Structure

| 操作 | 路径 | 职责 |
|------|------|------|
| Create | `adapters/__init__.py` | 包初始化 |
| Create | `adapters/model_config.py` | 模型配置桥接 |
| Create | `adapters/memory_adapters/__init__.py` | 适配器注册表 |
| Create | `adapters/memory_adapters/common.py` | 共享工具（数据转换、格式化） |
| Create | `adapters/memory_adapters/keyword_adapter.py` | Keyword 适配器 |
| Create | `adapters/memory_adapters/llm_only_adapter.py` | LLMOnly 适配器 |
| Create | `adapters/memory_adapters/embeddings_adapter.py` | Embeddings 适配器 |
| Create | `adapters/memory_adapters/memory_bank_adapter.py` | MemoryBank 适配器 |
| Create | `adapters/runner.py` | 评测管线运行器 |
| Create | `run_benchmark.py` | CLI 入口 |
| Modify | `config/llm.json` | 追加 benchmark 配置节 |
| Delete | `app/experiment/` | 旧实验代码 |
| Delete | `run_experiment.py` | 旧 CLI |
| Delete | `config/evaluation_config.json` | 旧评估配置 |
| Delete | `tests/` 中旧实验测试 | 旧测试 |
| Submodule | `vendor/VehicleMemBench` | 子模块 |

---

### Task 1: 添加 VehicleMemBench 子模块

**Files:**
- Create: `vendor/VehicleMemBench/` (git submodule)

- [ ] **Step 1: 添加 git submodule**

```bash
cd /home/miyakomeow/Codes/thesis-cockpit-memo
mkdir -p vendor
git submodule add https://github.com/isyuhaochen/VehicleMemBench.git vendor/VehicleMemBench
```

- [ ] **Step 2: 验证子模块可用**

```bash
ls vendor/VehicleMemBench/environment/vehicleworld.py vendor/VehicleMemBench/evaluation/eval_utils.py vendor/VehicleMemBench/evaluation/model_evaluation.py vendor/VehicleMemBench/benchmark/qa_data/ vendor/VehicleMemBench/benchmark/history/
```

Expected: 所有文件/目录存在

- [ ] **Step 3: Commit**

```bash
git add vendor/VehicleMemBench .gitmodules
git commit -m "chore: add VehicleMemBench as git submodule"
```

---

### Task 2: 扩展配置 + 创建 adapters 包骨架

**Files:**
- Modify: `config/llm.json`
- Create: `adapters/__init__.py`
- Create: `adapters/model_config.py`
- Test: `tests/test_adapters/__init__.py`
- Test: `tests/test_adapters/test_model_config.py`

- [ ] **Step 1: 写 model_config 测试**

```python
# tests/test_adapters/test_model_config.py
import os
import json
import pytest


def test_get_benchmark_client_returns_openai_instance(tmp_path, monkeypatch):
    config = {
        "llm": [{"model": "test-model", "base_url": "http://localhost:1234/v1", "api_key": "test"}],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client
    client = get_benchmark_client()
    assert client is not None
    assert hasattr(client, "chat")


def test_get_benchmark_client_uses_llm_config_when_no_benchmark(tmp_path, monkeypatch):
    config = {
        "llm": [{"model": "qwen3.5-2b", "base_url": "http://127.0.0.1:50721/v1", "api_key": "none"}],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client
    client = get_benchmark_client()
    assert client is not None


def test_get_benchmark_client_uses_benchmark_config_with_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test123")
    config = {
        "llm": [{"model": "qwen3.5-2b", "base_url": "http://127.0.0.1:50721/v1", "api_key": "none"}],
        "benchmark": {
            "model": "MiniMax-M2.7",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env": "TEST_API_KEY",
            "temperature": 0.0,
            "max_tokens": 8192,
        },
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client
    client = get_benchmark_client()
    assert client is not None


def test_get_store_chat_model(tmp_path, monkeypatch):
    config = {
        "llm": [{"model": "qwen3.5-2b", "base_url": "http://127.0.0.1:50721/v1", "api_key": "none"}],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_store_chat_model
    model = get_store_chat_model()
    assert model is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_model_config.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 更新 config/llm.json**

在现有配置后追加 `benchmark` 节：

```json
{
  "llm": [
    {
      "model": "qwen3.5-2b",
      "base_url": "http://127.0.0.1:50721/v1",
      "api_key": "none",
      "temperature": 0.7
    }
  ],
  "benchmark": {
    "model": "MiniMax-M2.7",
    "base_url": "https://api.minimaxi.com/v1",
    "api_key_env": "MINIMAX_API_KEY",
    "temperature": 0.0,
    "max_tokens": 8192
  },
  "embedding": [
    {
      "model": "BAAI/bge-small-zh-v1.5",
      "device": "cpu"
    }
  ]
}
```

- [ ] **Step 4: 创建 adapters/__init__.py**

```python
```

- [ ] **Step 5: 创建 tests/test_adapters/__init__.py**

```python
```

- [ ] **Step 6: 实现 adapters/model_config.py**

```python
import json
import os
from pathlib import Path

from openai import OpenAI

CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "config" / "llm.json")


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_benchmark_client() -> OpenAI:
    config = _load_config()
    if "benchmark" in config:
        bc = config["benchmark"]
        api_key = os.environ.get(bc.get("api_key_env", ""), bc.get("api_key", ""))
        return OpenAI(
            base_url=bc["base_url"],
            api_key=api_key,
        )
    llm = config["llm"][0]
    return OpenAI(
        base_url=llm.get("base_url"),
        api_key=llm.get("api_key", ""),
    )


def get_benchmark_model_name() -> str:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"]["model"]
    return config["llm"][0]["model"]


def get_benchmark_temperature() -> float:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("temperature", 0.0)
    return config["llm"][0].get("temperature", 0.7)


def get_benchmark_max_tokens() -> int:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("max_tokens", 8192)
    return 8192


def get_store_chat_model():
    from app.models.settings import get_chat_model
    return get_chat_model()


def get_store_embedding_model():
    from app.models.settings import get_embedding_model
    return get_embedding_model()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_model_config.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add config/llm.json adapters/__init__.py adapters/model_config.py tests/test_adapters/
git commit -m "feat: add adapters package with model config bridge"
```

---

### Task 3: 实现 common.py — 数据转换与格式化

**Files:**
- Create: `adapters/memory_adapters/__init__.py`
- Create: `adapters/memory_adapters/common.py`
- Test: `tests/test_adapters/test_common.py`

- [ ] **Step 1: 写 common 测试**

```python
# tests/test_adapters/test_common.py
from adapters.memory_adapters.common import (
    history_to_interaction_records,
    format_search_results,
    StoreClient,
)


SAMPLE_HISTORY = """[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3
[2025-03-03 08:31] Justin Martinez: That sounds comfortable
[2025-03-05 07:45] Gary Allen: When driving at night, I prefer the dashboard dim
"""


def test_history_to_interaction_records():
    records = history_to_interaction_records(SAMPLE_HISTORY)
    assert len(records) == 3
    assert records[0].content == "Gary Allen: I like the seat heating on level 3"
    assert records[0].date_group == "2025-03-03"
    assert records[1].date_group == "2025-03-03"
    assert records[2].date_group == "2025-03-05"


def test_history_to_interaction_records_empty():
    records = history_to_interaction_records("")
    assert records == []


def test_format_search_results_empty():
    text, count = format_search_results([])
    assert text == ""
    assert count == 0


def test_format_search_results_with_events():
    from app.memory.schemas import SearchResult
    results = [
        SearchResult(event={"content": "Gary prefers seat heating level 3", "id": "1"}, score=0.9),
        SearchResult(event={"content": "Gary likes dashboard dim at night", "id": "2"}, score=0.8),
    ]
    text, count = format_search_results(results)
    assert count == 2
    assert "seat heating" in text
    assert "dashboard dim" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_common.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 adapters/memory_adapters/__init__.py**

```python
from adapters.memory_adapters.keyword_adapter import KeywordAdapter
from adapters.memory_adapters.llm_only_adapter import LLMOnlyAdapter
from adapters.memory_adapters.embeddings_adapter import EmbeddingsAdapter
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter

ADAPTERS = {
    "keyword": KeywordAdapter,
    "llm_only": LLMOnlyAdapter,
    "embeddings": EmbeddingsAdapter,
    "memory_bank": MemoryBankAdapter,
}
```

- [ ] **Step 4: 实现 adapters/memory_adapters/common.py**

```python
import re
from app.memory.schemas import MemoryEvent


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    if not history_text.strip():
        return []
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+(.+)$")
    records = []
    for i, line in enumerate(history_text.strip().splitlines()):
        m = pattern.match(line)
        if m:
            date_group = m.group(1)
            content = m.group(2)
        else:
            date_group = "unknown"
            content = line
        records.append(
            MemoryEvent(
                id=f"hist_{i}",
                content=content,
                description=content,
                type="general",
                date_group=date_group,
                memory_strength=1,
            )
        )
    return records


def format_search_results(results) -> tuple[str, int]:
    if not results:
        return ("", 0)
    texts = []
    for r in results:
        event = r.event if hasattr(r, "event") else r
        if isinstance(event, dict):
            content = event.get("content", "")
        elif hasattr(event, "content"):
            content = event.content
        else:
            content = str(event)
        if content:
            texts.append(content)
    return ("\n".join(texts), len(texts))


class StoreClient:
    def __init__(self, store):
        self.store = store

    def search(self, query, user_id=None, top_k=5):
        return self.store.search(query=query, top_k=top_k)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_common.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add adapters/memory_adapters/__init__.py adapters/memory_adapters/common.py tests/test_adapters/test_common.py
git commit -m "feat: add memory adapter common utilities"
```

---

### Task 4: 实现 Keyword 适配器

**Files:**
- Create: `adapters/memory_adapters/keyword_adapter.py`
- Test: `tests/test_adapters/test_keyword_adapter.py`

- [ ] **Step 1: 写适配器测试**

```python
# tests/test_adapters/test_keyword_adapter.py
import pytest
from adapters.memory_adapters.keyword_adapter import KeywordAdapter


SAMPLE_HISTORY = """[2025-03-03 08:30] Gary Allen: I like the seat heating on level 3
[2025-03-05 07:45] Gary Allen: Set navigation volume to high
"""


def test_keyword_adapter_add_and_search(tmp_path):
    adapter = KeywordAdapter(data_dir=str(tmp_path))
    state = adapter.add(SAMPLE_HISTORY)
    assert state is not None
    client = adapter.get_search_client(state)
    results = client.search(query="seat heating", top_k=5)
    assert len(results) > 0


def test_keyword_adapter_tag():
    adapter = KeywordAdapter(data_dir="/tmp/dummy")
    assert adapter.TAG == "keyword"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_keyword_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 keyword_adapter.py**

```python
from adapters.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from app.memory.stores.keyword_store import KeywordMemoryStore


class KeywordAdapter:
    TAG = "keyword"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def add(self, history_text: str) -> KeywordMemoryStore:
        store = KeywordMemoryStore(data_dir=self.data_dir)
        records = history_to_interaction_records(history_text)
        for record in records:
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        return StoreClient(store)

    def init_state(self):
        return None

    def close_state(self, state):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_keyword_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/memory_adapters/keyword_adapter.py tests/test_adapters/test_keyword_adapter.py
git commit -m "feat: add keyword memory adapter"
```

---

### Task 5: 实现 LLMOnly 适配器

**Files:**
- Create: `adapters/memory_adapters/llm_only_adapter.py`
- Test: `tests/test_adapters/test_llm_only_adapter.py`

- [ ] **Step 1: 写适配器测试**

```python
# tests/test_adapters/test_llm_only_adapter.py
from adapters.memory_adapters.llm_only_adapter import LLMOnlyAdapter


def test_llm_only_adapter_tag():
    adapter = LLMOnlyAdapter.__new__(LLMOnlyAdapter)
    assert adapter.TAG == "llm_only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_llm_only_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 llm_only_adapter.py**

```python
from adapters.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from adapters.model_config import get_store_chat_model
from app.memory.stores.llm_store import LLMOnlyMemoryStore


class LLMOnlyAdapter:
    TAG = "llm_only"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def add(self, history_text: str) -> LLMOnlyMemoryStore:
        chat_model = get_store_chat_model()
        store = LLMOnlyMemoryStore(data_dir=self.data_dir, chat_model=chat_model)
        records = history_to_interaction_records(history_text)
        for record in records:
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        return StoreClient(store)

    def init_state(self):
        return None

    def close_state(self, state):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_llm_only_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/memory_adapters/llm_only_adapter.py tests/test_adapters/test_llm_only_adapter.py
git commit -m "feat: add llm_only memory adapter"
```

---

### Task 6: 实现 Embeddings 适配器

**Files:**
- Create: `adapters/memory_adapters/embeddings_adapter.py`
- Test: `tests/test_adapters/test_embeddings_adapter.py`

- [ ] **Step 1: 写适配器测试**

```python
# tests/test_adapters/test_embeddings_adapter.py
from adapters.memory_adapters.embeddings_adapter import EmbeddingsAdapter


def test_embeddings_adapter_tag():
    adapter = EmbeddingsAdapter.__new__(EmbeddingsAdapter)
    assert adapter.TAG == "embeddings"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_embeddings_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 embeddings_adapter.py**

```python
from adapters.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from adapters.model_config import get_store_embedding_model
from app.memory.stores.embedding_store import EmbeddingMemoryStore


class EmbeddingsAdapter:
    TAG = "embeddings"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def add(self, history_text: str) -> EmbeddingMemoryStore:
        embedding_model = get_store_embedding_model()
        store = EmbeddingMemoryStore(
            data_dir=self.data_dir, embedding_model=embedding_model
        )
        records = history_to_interaction_records(history_text)
        for record in records:
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        return StoreClient(store)

    def init_state(self):
        return None

    def close_state(self, state):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_embeddings_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/memory_adapters/embeddings_adapter.py tests/test_adapters/test_embeddings_adapter.py
git commit -m "feat: add embeddings memory adapter"
```

---

### Task 7: 实现 MemoryBank 适配器

**Files:**
- Create: `adapters/memory_adapters/memory_bank_adapter.py`
- Test: `tests/test_adapters/test_memory_bank_adapter.py`

- [ ] **Step 1: 写适配器测试**

```python
# tests/test_adapters/test_memory_bank_adapter.py
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter


def test_memory_bank_adapter_tag():
    adapter = MemoryBankAdapter.__new__(MemoryBankAdapter)
    assert adapter.TAG == "memory_bank"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_memory_bank_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 memory_bank_adapter.py**

```python
from adapters.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from adapters.model_config import get_store_chat_model, get_store_embedding_model
from app.memory.stores.memory_bank_store import MemoryBankStore


class MemoryBankAdapter:
    TAG = "memory_bank"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def add(self, history_text: str) -> MemoryBankStore:
        chat_model = get_store_chat_model()
        embedding_model = get_store_embedding_model()
        store = MemoryBankStore(
            data_dir=self.data_dir,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        records = history_to_interaction_records(history_text)
        for record in records:
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        return StoreClient(store)

    def init_state(self):
        return None

    def close_state(self, state):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_memory_bank_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/memory_adapters/memory_bank_adapter.py tests/test_adapters/test_memory_bank_adapter.py
git commit -m "feat: add memory_bank adapter"
```

---

### Task 8: 实现 runner.py — 评测管线核心

**Files:**
- Create: `adapters/runner.py`
- Test: `tests/test_adapters/test_runner.py`

这是最复杂的任务。runner.py 需要：

1. 将 `vendor/VehicleMemBench` 加入 `sys.path`
2. 导入 VehicleMemBench 底层函数
3. 编排 prepare/run/report 三阶段管线
4. 基线模式（gold/summary/kv）调用 VehicleMemBench 原生函数
5. 自研后端模式调用适配器 + 自写工具调用循环

- [ ] **Step 1: 写 runner 测试**

```python
# tests/test_adapters/test_runner.py
import pytest
from adapters.runner import setup_vehiclemembench_path


def test_setup_vehiclemembench_path():
    setup_vehiclemembench_path()
    import importlib
    spec = importlib.util.find_spec("environment.vehicleworld")
    assert spec is not None


def test_parse_file_range():
    from adapters.runner import parse_file_range
    assert parse_file_range("1-5") == [1, 2, 3, 4, 5]
    assert parse_file_range("1,3,5") == [1, 3, 5]
    assert parse_file_range("1-3,7") == [1, 2, 3, 7]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_runner.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 adapters/runner.py**

```python
import sys
import os
import json
import re
from pathlib import Path
from typing import Optional

from adapters.memory_adapters import ADAPTERS
from adapters.memory_adapters.common import format_search_results, StoreClient
from adapters.model_config import (
    get_benchmark_client,
    get_benchmark_model_name,
    get_benchmark_temperature,
    get_benchmark_max_tokens,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "VehicleMemBench"
BENCHMARK_DIR = VENDOR_DIR / "benchmark"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark"


def setup_vehiclemembench_path():
    vendor_str = str(VENDOR_DIR)
    for p in sys.path:
        if os.path.abspath(p) == os.path.abspath(vendor_str):
            return
    sys.path.insert(0, vendor_str)


setup_vehiclemembench_path()

from environment.vehicleworld import VehicleWorld
from evaluation.eval_utils import calculate_turn_result, score_tool_calls
from evaluation.model_evaluation import (
    parse_answer_to_tools,
    get_functions_schema_for_module,
    get_list_module_tools_schema,
    build_tool_env,
    split_history_by_day,
    build_memory_recursive_summary,
    build_memory_key_value,
    process_task_direct,
    process_task_with_memory,
    process_task_with_kv_memory,
    _build_metric,
    _run_vehicle_task_evaluation,
    MemoryStore as VMBMemoryStore,
)
from evaluation.agent_client import AgentClient


def parse_file_range(range_str: str) -> list[int]:
    result = []
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            result.extend(range(int(a), int(b) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def _get_agent_client() -> AgentClient:
    client = get_benchmark_client()
    return AgentClient(
        api_base=client.base_url,
        api_key=client.api_key,
        model=get_benchmark_model_name(),
        temperature=get_benchmark_temperature(),
        max_tokens=get_benchmark_max_tokens(),
    )


def _load_qa(file_num: int) -> dict:
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    with open(path) as f:
        return json.load(f)


def _load_history(file_num: int) -> str:
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    with open(path) as f:
        return f.read()


def _get_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def prepare(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,keyword,llm_only,embeddings,memory_bank",
):
    file_nums = parse_file_range(file_range)
    types = [t.strip() for t in memory_types.split(",")]
    agent_client = _get_agent_client()
    output_dir = _get_output_dir()

    for fnum in file_nums:
        history_text = _load_history(fnum)
        for mtype in types:
            result_path = output_dir / f"{mtype}_file_{fnum}.json"
            if result_path.exists():
                print(f"[skip] {mtype} file {fnum} already prepared")
                continue

            print(f"[prepare] {mtype} file {fnum}...")
            try:
                result = _prepare_single(agent_client, history_text, fnum, mtype)
                if result is not None:
                    with open(result_path, "w") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[error] {mtype} file {fnum}: {e}")
                continue


def _prepare_single(agent_client, history_text, file_num, memory_type):
    if memory_type == "gold":
        return {"type": "gold"}
    if memory_type == "summary":
        daily = split_history_by_day(history_text)
        mem_text, _, _ = build_memory_recursive_summary(agent_client, daily)
        return {"type": "summary", "memory_text": mem_text}
    if memory_type == "kv":
        daily = split_history_by_day(history_text)
        store, _, _ = build_memory_key_value(agent_client, daily)
        return {"type": "kv", "store": store.to_dict()}
    if memory_type in ADAPTERS:
        adapter_cls = ADAPTERS[memory_type]
        data_dir = str(_get_output_dir() / f"store_{memory_type}_{file_num}")
        adapter = adapter_cls(data_dir=data_dir)
        store = adapter.add(history_text)
        return {"type": memory_type, "data_dir": data_dir}
    return None


def run(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,keyword,llm_only,embeddings,memory_bank",
    reflect_num: int = 10,
):
    file_nums = parse_file_range(file_range)
    types = [t.strip() for t in memory_types.split(",")]
    agent_client = _get_agent_client()
    output_dir = _get_output_dir()

    for fnum in file_nums:
        qa_data = _load_qa(fnum)
        history_text = _load_history(fnum)
        events = qa_data.get("related_to_vehicle_preference", [])
        for mtype in types:
            result_path = output_dir / f"{mtype}_file_{fnum}_results.json"
            prep_path = output_dir / f"{mtype}_file_{fnum}.json"
            if not prep_path.exists():
                print(f"[skip] {mtype} file {fnum} not prepared")
                continue

            with open(prep_path) as f:
                prep_data = json.load(f)

            print(f"[run] {mtype} file {fnum}: {len(events)} queries...")
            try:
                results = _run_single(
                    agent_client, events, history_text, prep_data, fnum, mtype, reflect_num
                )
                with open(result_path, "w") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[error] {mtype} file {fnum}: {e}")
                continue


def _run_single(agent_client, events, history_text, prep_data, file_num, memory_type, reflect_num):
    results = []
    for i, event in enumerate(events):
        query = event.get("query", "")
        reasoning_type = event.get("reasoning_type", "")
        ref_calls = parse_answer_to_tools(event.get("new_answer", []))
        gold_memory = event.get("gold_memory", "")
        task = {"query": query, "tools": ref_calls, "reasoning_type": reasoning_type}

        try:
            if memory_type == "gold":
                task["history_text"] = gold_memory
                result = process_task_direct(task, i, agent_client, reflect_num)
            elif memory_type == "summary":
                memory_text = prep_data.get("memory_text", "")
                result = process_task_with_memory(
                    task, i, memory_text, agent_client, reflect_num
                )
            elif memory_type == "kv":
                vmb_store = VMBMemoryStore()
                vmb_store.store = prep_data.get("store", {})
                result = process_task_with_kv_memory(
                    task, i, vmb_store, agent_client, reflect_num
                )
            elif memory_type in ADAPTERS:
                result = _run_custom_adapter(
                    agent_client, task, i, prep_data, memory_type, reflect_num
                )
            else:
                continue

            if result:
                result["source_file"] = file_num
                result["event_index"] = i
                result["memory_type"] = memory_type
                results.append(result)
        except Exception as e:
            print(f"  [error] query {i}: {e}")
            continue

    return results


def _run_custom_adapter(agent_client, task, task_id, prep_data, memory_type, reflect_num):
    adapter_cls = ADAPTERS[memory_type]
    data_dir = prep_data["data_dir"]
    adapter = adapter_cls(data_dir=data_dir)

    store = adapter.add("")
    client = adapter.get_search_client(store)

    system_instruction = (
        "You are an intelligent in-car AI assistant responsible for fulfilling user requests by calling the vehicle system API.\n"
        "You have access to a memory store containing user vehicle preferences.\n"
        "- Use memory_search(query, top_k) to look up relevant user preferences\n"
        "- Use list_module_tools(module_name='xxx') to discover available functions\n"
        "- Call the specific functions you need\n"
        "When the available information does not support setting a device to a specific value, "
        "perform only the minimal required action."
    )

    initial_tools = [
        {"type": "function", "function": get_list_module_tools_schema()},
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search user vehicle preferences by keyword",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    def _memory_search(query, top_k=5):
        results = client.search(query=query, top_k=top_k)
        text, count = format_search_results(results)
        return {"success": True, "results": text, "count": count}

    memory_funcs = {
        "memory_search": _memory_search,
    }

    return _run_vehicle_task_evaluation(
        task=task,
        task_id=task_id,
        agent_client=agent_client,
        reflect_num=reflect_num,
        system_instruction=system_instruction,
        request_context=f"{memory_type} file task {task_id}",
        initial_tools=initial_tools,
        memory_funcs=memory_funcs,
    )


def report(output_path: Optional[str] = None):
    output_dir = _get_output_dir()
    all_results = {}

    for path in sorted(output_dir.glob("*_results.json")):
        mtype = path.stem.replace("_results", "").rsplit("_file_", 1)[0]
        with open(path) as f:
            results = json.load(f)
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].extend(results)

    report_data = {}
    for mtype, results in all_results.items():
        metric = _build_metric(results, model=get_benchmark_model_name(), memory_type=mtype)
        report_data[mtype] = metric

    if "gold" in report_data:
        gold_esm = report_data["gold"].get("exact_match_rate", 0)
        for mtype in report_data:
            if mtype != "gold":
                auto_esm = report_data[mtype].get("exact_match_rate", 0)
                report_data[mtype]["memory_score"] = (
                    auto_esm / gold_esm if gold_esm > 0 else 0.0
                )

    out = output_path or str(output_dir / "report.json")
    with open(out, "w") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"Report written to {out}")

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        print(f"  {mtype}: ESM={esm:.2%}, F-F1={metric.get('state_f1_positive', 0):.4f}, "
              f"V-F1={metric.get('state_f1_change', 0):.4f}, "
              f"Calls={metric.get('avg_pred_calls', 0):.1f}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/test_adapters/test_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/runner.py tests/test_adapters/test_runner.py
git commit -m "feat: add benchmark runner with VehicleMemBench integration"
```

---

### Task 9: 实现 run_benchmark.py CLI

**Files:**
- Create: `run_benchmark.py`

- [ ] **Step 1: 实现 CLI**

```python
import argparse
from adapters.runner import prepare, run, report


def main():
    parser = argparse.ArgumentParser(description="VehicleMemBench evaluation")
    subparsers = parser.add_subparsers(dest="command")

    for cmd in ["prepare", "run", "all"]:
        p = subparsers.add_parser(cmd)
        p.add_argument("--file-range", default="1-50")
        p.add_argument("--memory-types", default="gold,summary,kv,keyword,llm_only,embeddings,memory_bank")
        p.add_argument("--max-workers", type=int, default=1)
        p.add_argument("--output-dir", default=None)

    rp = subparsers.add_parser("report")
    rp.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "prepare":
        prepare(args.file_range, args.memory_types)
    elif args.command == "run":
        run(args.file_range, args.memory_types)
    elif args.command == "report":
        report(args.output)
    elif args.command == "all":
        prepare(args.file_range, args.memory_types)
        run(args.file_range, args.memory_types)
        report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 CLI 可加载**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python run_benchmark.py --help`
Expected: 显示帮助信息

- [ ] **Step 3: Commit**

```bash
git add run_benchmark.py
git commit -m "feat: add run_benchmark.py CLI entry point"
```

---

### Task 10: 删除旧实验代码

**Files:**
- Delete: `app/experiment/` 整个目录
- Delete: `run_experiment.py`
- Delete: `config/evaluation_config.json`
- Delete: `tests/` 中旧实验测试文件
- Delete: `data/` 中旧实验输出（保留 `data/` 骨架）

- [ ] **Step 1: 删除旧实验代码**

```bash
cd /home/miyakomeow/Codes/thesis-cockpit-memo
rm -rf app/experiment/
rm run_experiment.py
rm -f config/evaluation_config.json
```

- [ ] **Step 2: 删除旧实验测试**

```bash
cd /home/miyakomeow/Codes/thesis-cockpit-memo
rm -f tests/test_evaluate.py tests/test_execute.py tests/test_judge.py
rm -f tests/test_prepare.py tests/test_experiment_runner.py tests/test_e2e_pipeline.py
```

- [ ] **Step 3: 清理 data/ 中旧实验输出**

```bash
cd /home/miyakomeow/Codes/thesis-cockpit-memo
# 保留核心 JSON 文件骨架，删除旧实验目录
find data/ -maxdepth 1 -type d \( -name 'test_*' -o -name 'exp_*' -o -name 'final_*' -o -name 'r_*' \) -exec rm -rf {} +
```

- [ ] **Step 4: 验证项目仍可导入**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -c "from app.memory.memory import MemoryModule; print('OK')"`
Expected: OK

- [ ] **Step 5: 验证剩余测试仍通过**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/ -v --ignore=tests/test_adapters -x`
Expected: 旧实验测试已删，剩余测试通过

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove old experiment system"
```

---

### Task 11: 端到端验证

**Files:**
- 无新文件

- [ ] **Step 1: 验证完整导入链**

```bash
cd /home/miyakomeow/Codes/thesis-cockpit-memo
python -c "
from adapters.runner import prepare, run, report, setup_vehiclemembench_path
from adapters.memory_adapters import ADAPTERS
from adapters.model_config import get_benchmark_client
print('Imports OK')
print('Adapters:', list(ADAPTERS.keys()))
"
```

Expected: 无错误

- [ ] **Step 2: 运行全部测试**

Run: `cd /home/miyakomeow/Codes/thesis-cockpit-memo && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit (如有修改)**

```bash
git add -A
git commit -m "fix: resolve integration issues from e2e verification"
```
