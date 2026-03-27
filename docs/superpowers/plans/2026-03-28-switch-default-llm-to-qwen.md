# 切换默认 LLM 至 qwen3.5-2b 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目默认 LLM 从 DeepSeek 切换为本地 vLLM 部署的 Qwen3.5-2B，DeepSeek 保留为手动可切换的备用。

**Architecture:** 修改 `config.py` 注册表和 `chat.py` 默认参数。新增 `conftest.py` 提供 vLLM 可用性检测，替换测试文件中的 skip 条件。所有 LLM 调用通过 `ChatModel` 间接生效，业务代码无需改动。

**Tech Stack:** Python, pytest, langchain-openai, vLLM (OpenAI compatible)

---

### Task 1: 新增 vLLM 可用性检测 (conftest.py)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 conftest.py，提供 vLLM 可用性检测函数**

```python
import urllib.request
import urllib.error


def is_vllm_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:8000/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def is_vllm_unavailable() -> bool:
    return not is_vllm_available()
```

- [ ] **Step 2: 验证 conftest 可被 pytest 发现**

Run: `uv run pytest tests/ --collect-only 2>&1 | head -20`
Expected: 测试收集正常，无 import 错误

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add vLLM availability detection in conftest"
```

---

### Task 2: 修改 config.py — 新增 qwen 提供商，切换默认

**Files:**
- Modify: `app/models/config.py`

- [ ] **Step 1: 在 PROVIDERS 中新增 qwen 条目，将 get_provider 默认值改为 qwen**

将 `app/models/config.py` 整体替换为：

```python
"""模型配置，支持 qwen、DeepSeek 和其他 OpenAI 兼容接口"""


class ModelConfig:
    """模型配置"""

    PROVIDERS = {
        "qwen": {
            "base_url": "http://localhost:8000/v1",
            "model": "Qwen/Qwen3.5-2B",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
        "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4"},
        "anthropic": {
            "base_url": "https://api.anthropic.com",
            "model": "claude-3-sonnet-20240229",
        },
    }

    @classmethod
    def get_provider(cls, name: str = "qwen"):
        return cls.PROVIDERS.get(name, cls.PROVIDERS["qwen"])
```

- [ ] **Step 2: 验证现有 mock 测试仍然通过**

Run: `uv run pytest tests/test_memory_bank.py tests/test_experiment_runner.py tests/test_storage.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add app/models/config.py
git commit -m "feat: add qwen as default provider in config, deepseek as fallback"
```

---

### Task 3: 修改 chat.py — 切换默认模型和 base_url

**Files:**
- Modify: `app/models/chat.py`

- [ ] **Step 1: 修改默认参数，使 api_key 可选（vLLM 不需要 key）**

将 `ChatModel.__init__` 的默认参数和 api_key 逻辑改为：

```python
class ChatModel:
    def __init__(
        self,
        model: str = "Qwen/Qwen3.5-2B",
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: str = "http://localhost:8000/v1",
    ):
        self.model_name = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
```

同时删除原有的 `os.getenv("DEEPSEEK_API_KEY")` 回退和 `raise ValueError` 逻辑（第 18-22 行）。保留 `os` import 以防其他地方使用，或如果无其他使用则删除 `import os`。

`client` property 中已处理 `api_key_str` 为空的情况（传 `None` 给 `openai_api_key`），无需修改。

- [ ] **Step 2: 验证 mock 测试仍通过**

Run: `uv run pytest tests/test_memory_bank.py tests/test_experiment_runner.py tests/test_storage.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add app/models/chat.py
git commit -m "feat: switch ChatModel defaults to qwen3.5-2b via vLLM"
```

---

### Task 4: 修改 test_chat.py — 使用 vLLM 检测跳过

**Files:**
- Modify: `tests/test_chat.py`

- [ ] **Step 1: 将 skip 条件从 DEEPSEEK_API_KEY 改为 vLLM 可用性**

将文件替换为：

```python
import pytest

from app.memory.memory import MemoryModule
from app.models.chat import ChatModel
from tests.conftest import is_vllm_unavailable

SKIP_IF_NO_VLLM = pytest.mark.skipif(
    is_vllm_unavailable(),
    reason="vLLM not available at http://localhost:8000",
)


@SKIP_IF_NO_VLLM
def test_chat_drives_llm_memory_search(tmp_path):
    chat_model = ChatModel()
    memory = MemoryModule(str(tmp_path), chat_model=chat_model)
    memory.write({"content": "明天下午三点项目会议", "type": "meeting"})
    results = memory.search("有什么会议安排", mode="llm_only")
    assert len(results) > 0
    assert "会议" in results[0]["content"]


@SKIP_IF_NO_VLLM
def test_chat_feeds_workflow_context(tmp_path):
    from app.agents.workflow import AgentWorkflow
    from langchain_core.messages import HumanMessage

    memory = MemoryModule(str(tmp_path), chat_model=ChatModel())
    memory.write({"content": "下午三点开会", "type": "meeting"})
    workflow = AgentWorkflow(memory_module=memory)
    state = {
        "messages": [HumanMessage(content="查一下会议")],
        "context": {},
        "task": None,
        "decision": None,
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert "related_events" in result["context"]
```

- [ ] **Step 2: 运行测试（vLLM 不可用时应 SKIP）**

Run: `uv run pytest tests/test_chat.py -v`
Expected: 2 tests SKIPPED (如果 vLLM 未运行) 或 2 PASSED (如果 vLLM 运行中)

- [ ] **Step 3: Commit**

```bash
git add tests/test_chat.py
git commit -m "test: switch chat tests to vLLM availability check"
```

---

### Task 5: 修改 test_api.py — 使用 vLLM 检测跳过

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: 将 skip 条件从 DEEPSEEK_API_KEY 改为 vLLM 可用性**

将文件替换为：

```python
from fastapi.testclient import TestClient

import pytest

from tests.conftest import is_vllm_unavailable

SKIP_IF_NO_VLLM = pytest.mark.skipif(
    is_vllm_unavailable(),
    reason="vLLM not available at http://localhost:8000",
)


@pytest.fixture
def client():
    from app.api.main import app

    return TestClient(app)


@SKIP_IF_NO_VLLM
def test_query_endpoint(client):
    response = client.post(
        "/api/query", json={"query": "测试查询", "memory_mode": "keyword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "event_id" in data


@SKIP_IF_NO_VLLM
def test_feedback_endpoint(client):
    response = client.post(
        "/api/feedback", json={"event_id": "test123", "action": "accept"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@SKIP_IF_NO_VLLM
def test_history_endpoint(client):
    response = client.get("/api/history?limit=5")
    assert response.status_code == 200
    assert "history" in response.json()
```

- [ ] **Step 2: 运行测试（vLLM 不可用时应 SKIP）**

Run: `uv run pytest tests/test_api.py -v`
Expected: 3 tests SKIPPED (如果 vLLM 未运行) 或 3 PASSED (如果 vLLM 运行中)

- [ ] **Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "test: switch API tests to vLLM availability check"
```

---

### Task 6: 全量测试验证

**Files:** 无新改动

- [ ] **Step 1: 运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: 所有 mock 测试 PASS，integration 测试 SKIP（vLLM 未运行时）或 PASS（vLLM 运行时）

- [ ] **Step 2: 运行 lint 检查**

Run: `uv run ruff check .`
Expected: 无错误

- [ ] **Step 3: 确认无遗留的 DEEPSEEK_API_KEY 引用（在测试 skip 条件中）**

Run: `grep -r "DEEPSEEK_API_KEY" tests/`
Expected: 无输出（已全部替换）
