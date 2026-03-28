# Memory Mode 类型深度重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除所有 `memory_mode` 硬编码字符串匹配，Store 类自声明能力依赖。

**Architecture:** 引入 `MemoryMode(StrEnum)` 作为全局唯一真值源；Store 基类新增 `requires_embedding`/`requires_chat`/`supports_interaction` 类属性；MemoryModule 工厂方法根据类属性自动加载依赖；AgentWorkflow 消除所有字符串条件分支。

**Tech Stack:** Python 3.13, StrEnum, Pydantic, FastAPI, LangGraph, pytest

---

### Task 1: 创建 MemoryMode 枚举

**Files:**
- Create: `app/memory/types.py`
- Test: `tests/test_memory_types.py`

- [ ] **Step 1: 创建 `app/memory/types.py`**

```python
"""记忆模式枚举定义."""

from enum import StrEnum


class MemoryMode(StrEnum):
    """记忆检索模式."""

    KEYWORD = "keyword"
    LLM_ONLY = "llm_only"
    EMBEDDINGS = "embeddings"
    MEMORY_BANK = "memorybank"
```

- [ ] **Step 2: 写测试验证 StrEnum 兼容性**

```python
"""MemoryMode 枚举测试."""

from app.memory.types import MemoryMode


def test_str_enum_compat():
    assert MemoryMode.KEYWORD == "keyword"
    assert MemoryMode.KEYWORD in ["keyword", "llm_only"]


def test_all_values():
    assert set(MemoryMode) == {
        MemoryMode.KEYWORD,
        MemoryMode.LLM_ONLY,
        MemoryMode.EMBEDDINGS,
        MemoryMode.MEMORY_BANK,
    }
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_memory_types.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/memory/types.py tests/test_memory_types.py
git commit -m "feat(memory): add MemoryMode StrEnum"
```

---

### Task 2: Store 接口新增 write_interaction + BaseMemoryStore 能力声明

**Files:**
- Modify: `app/memory/interfaces.py:6-33`
- Modify: `app/memory/stores/base.py:9-76`
- Test: `tests/test_memory_module_facade.py`（已有，验证兼容）

- [ ] **Step 1: 修改 `app/memory/interfaces.py`，新增 `write_interaction` 抽象方法**

在 `update_feedback` 方法后新增：

```python
@abstractmethod
def write_interaction(
    self, query: str, response: str, event_type: str = "reminder"
) -> str:
    """写入交互记录，返回 event_id."""
    pass
```

- [ ] **Step 2: 修改 `app/memory/stores/base.py`，新增类属性和默认实现**

在 `BaseMemoryStore` 类体开头（`def __init__` 前）添加：

```python
requires_embedding: bool = False
requires_chat: bool = False
supports_interaction: bool = False
```

在类体末尾（`_update_strategy` 方法后）添加：

```python
def write_interaction(
    self, query: str, response: str, event_type: str = "reminder"
) -> str:
    return self.write({"content": response, "type": event_type})
```

基类默认将交互记录包装为普通事件写入，`MemoryBankStore` 覆写此方法提供完整的聚合逻辑。

- [ ] **Step 3: 更新 `tests/test_memory_module_facade.py`**

`test_write_interaction_raises_for_non_memorybank` 现在不应抛异常。将测试改为验证 keyword 模式下 `write_interaction` 回退到 `write`：

```python
def test_write_interaction_falls_back_to_write_for_non_memorybank(self, mm):
    """Verify write_interaction falls back to write for non-memorybank modes."""
    mm.set_default_mode("keyword")
    interaction_id = mm.write_interaction("q", "r")
    assert isinstance(interaction_id, str)
    history = mm.get_history()
    assert len(history) == 1
    assert history[0]["content"] == "r"
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_memory_module_facade.py tests/test_memory_store_contract.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/memory/interfaces.py app/memory/stores/base.py
git commit -m "feat(memory): add write_interaction to interface and capability flags to base"
```

---

### Task 3: 各 Store 设置能力类属性

**Files:**
- Modify: `app/memory/stores/llm_store.py:30` — 新增 `requires_chat = True`
- Modify: `app/memory/stores/embedding_store.py:14` — 新增 `requires_embedding = True`
- Modify: `app/memory/stores/memory_bank_store.py:28` — 新增三个类属性

- [ ] **Step 1: 修改 `app/memory/stores/llm_store.py`**

在 `LLMOnlyMemoryStore` 类体开头（`def __init__` 前）添加：

```python
requires_chat: bool = True
```

- [ ] **Step 2: 修改 `app/memory/stores/embedding_store.py`**

在 `EmbeddingMemoryStore` 类体开头（`def __init__` 前）添加：

```python
requires_embedding: bool = True
```

- [ ] **Step 3: 修改 `app/memory/stores/memory_bank_store.py`**

在 `MemoryBankStore` 类体开头（`def __init__` 前）添加：

```python
requires_embedding: bool = True
requires_chat: bool = True
supports_interaction: bool = True
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_memory_store_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/stores/llm_store.py app/memory/stores/embedding_store.py app/memory/stores/memory_bank_store.py
git commit -m "feat(memory): set capability flags on each store implementation"
```

---

### Task 4: MemoryModule 使用 MemoryMode 注册表 + 按能力加载模型

**Files:**
- Modify: `app/memory/memory.py:1-108`
- Test: `tests/test_memory_module_facade.py`

- [ ] **Step 1: 重写 `app/memory/memory.py`**

完整替换文件内容为：

```python
"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

from typing import Any, Optional, TYPE_CHECKING

from app.memory.interfaces import MemoryStore
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]] = {}


def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    """注册 MemoryStore 实现类，用于工厂创建."""
    _STORES_REGISTRY[name] = store_cls


def _import_all_stores() -> None:
    """延迟导入所有 store 类并注册到工厂注册表."""
    from app.memory.stores.keyword_store import KeywordMemoryStore
    from app.memory.stores.llm_store import LLMOnlyMemoryStore
    from app.memory.stores.embedding_store import EmbeddingMemoryStore
    from app.memory.stores.memory_bank_store import MemoryBankStore

    register_store(MemoryMode.KEYWORD, KeywordMemoryStore)
    register_store(MemoryMode.LLM_ONLY, LLMOnlyMemoryStore)
    register_store(MemoryMode.EMBEDDINGS, EmbeddingMemoryStore)
    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ):
        """初始化 MemoryModule 实例.

        Args:
            data_dir: 数据存储目录.
            embedding_model: 向量嵌入模型 (可选，未传则按需加载).
            chat_model: 聊天模型 (可选，未传则按需加载).

        """
        _import_all_stores()
        self._stores: dict[MemoryMode, MemoryStore] = {}
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._default_mode: MemoryMode = MemoryMode.MEMORY_BANK

    @property
    def chat_model(self):
        """返回聊天模型实例."""
        if self._chat_model is None:
            from app.models.settings import get_chat_model
            self._chat_model = get_chat_model()
        return self._chat_model

    def _get_store(self, mode: MemoryMode) -> MemoryStore:
        """懒加载获取指定模式的 store."""
        if mode not in self._stores:
            self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _create_store(self, mode: MemoryMode) -> MemoryStore:
        """工厂方法创建 store，根据 Store 类属性按需加载模型."""
        if mode not in _STORES_REGISTRY:
            raise ValueError(
                f"Unknown mode: {mode}. Available: {list(_STORES_REGISTRY.keys())}"
            )
        store_cls = _STORES_REGISTRY[mode]
        kwargs: dict[str, Any] = {"data_dir": self._data_dir}
        if store_cls.requires_embedding:
            if self._embedding_model is None:
                from app.models.settings import get_embedding_model
                self._embedding_model = get_embedding_model()
            kwargs["embedding_model"] = self._embedding_model
        if store_cls.requires_chat:
            if self._chat_model is None:
                from app.models.settings import get_chat_model
                self._chat_model = get_chat_model()
            kwargs["chat_model"] = self._chat_model
        return store_cls(**kwargs)

    def set_default_mode(self, mode: MemoryMode) -> None:
        """设置默认模式."""
        if mode not in _STORES_REGISTRY:
            raise ValueError(f"Unknown mode: {mode}")
        self._default_mode = mode

    def write(self, event: dict) -> str:
        """写入事件到当前模式的 store."""
        store = self._get_store(self._default_mode)
        return store.write(event)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        store = self._get_store(self._default_mode)
        return store.write_interaction(query, response, event_type)

    def search(self, query: str, mode: MemoryMode | None = None) -> list:
        """检索记忆."""
        target_mode = mode or self._default_mode
        return self._get_store(target_mode).search(query)

    def get_history(self, limit: int = 10) -> list:
        """获取历史记录."""
        return self._get_store(self._default_mode).get_history(limit)

    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈."""
        self._get_store(self._default_mode).update_feedback(event_id, feedback)
```

关键变化：
- 注册表 `dict[MemoryMode, type[MemoryStore]]`
- `_create_store` 根据 `store_cls.requires_*` 按需加载模型
- `write_interaction` 直接委托给 store，移除 `hasattr` 检查
- `chat_model` property 改为按需加载

- [ ] **Step 2: 运行 Facade 测试**

Run: `pytest tests/test_memory_module_facade.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/memory/memory.py
git commit -m "refactor(memory): MemoryModule uses MemoryMode registry and capability-based model loading"
```

---

### Task 5: AgentWorkflow 消除字符串分支

**Files:**
- Modify: `app/agents/workflow.py:18-226`
- Test: `tests/test_experiment_runner.py`, `tests/test_chat.py`

- [ ] **Step 1: 修改 `app/agents/workflow.py`**

改动点：

1. 添加导入：
```python
from app.memory.types import MemoryMode
```

2. `__init__` 签名和初始化（`workflow.py:21-48`）：

```python
def __init__(
    self,
    data_dir: str = "data",
    memory_mode: MemoryMode = MemoryMode.KEYWORD,
    memory_module: Optional[MemoryModule] = None,
):
    """初始化工作流实例."""
    self.data_dir = data_dir
    self.memory_mode = memory_mode

    if memory_module is not None:
        self.memory_module = memory_module
    else:
        from app.models.settings import get_chat_model

        chat_model = get_chat_model()
        self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

    self.memory_module.set_default_mode(memory_mode)
    self.graph = self._build_graph()
```

删除了 `if memory_mode in ("embeddings", "memorybank")` 分支和 `_embedding_model` 属性。

3. `_execution_node`（`workflow.py:188-192`）：

将：
```python
if self.memory_mode == "memorybank":
    event_id = self.memory_module.write_interaction(user_input, content)
else:
    event_data = {"content": content, "type": "reminder", "decision": decision}
    event_id = self.memory_module.write(event_data)
```

替换为：
```python
event_id = self.memory_module.write_interaction(user_input, content)
```

4. `create_workflow` 函数（`workflow.py:222-226`）：

```python
def create_workflow(
    data_dir: str = "data", memory_mode: str = "keyword"
) -> AgentWorkflow:
    """创建工作流实例."""
    return AgentWorkflow(data_dir, MemoryMode(memory_mode))
```

- [ ] **Step 2: 运行相关测试**

Run: `pytest tests/test_experiment_runner.py tests/test_chat.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor(agents): eliminate memory_mode string branching in AgentWorkflow"
```

---

### Task 6: API、ExperimentRunner、CLI 适配 MemoryMode

**Files:**
- Modify: `app/api/main.py:1-105`
- Modify: `app/experiment/runner.py:229-235`
- Modify: `run_experiment.py:120,231-234`

- [ ] **Step 1: 修改 `app/api/main.py`**

1. 添加导入：
```python
from app.memory.types import MemoryMode
```

2. 删除 `from typing import Optional, Literal` 中的 `Literal`，改为：
```python
from typing import Optional
```

3. `QueryRequest`（`main.py:43`）：
```python
memory_mode: MemoryMode = MemoryMode.KEYWORD
```

- [ ] **Step 2: 修改 `app/experiment/runner.py`**

1. 添加导入（在文件顶部 import 区域）：
```python
from app.memory.types import MemoryMode
```

2. `run_comparison` 方法（`runner.py:229-231`）：
```python
valid_methods = set(MemoryMode)
if methods is None:
    methods = [m.value for m in MemoryMode]
```

- [ ] **Step 3: 修改 `run_experiment.py`**

1. 添加导入（在 `from app.experiment.runner import ExperimentRunner` 后）：
```python
from app.memory.types import MemoryMode
```

2. 默认方法列表（`run_experiment.py:120`）：
```python
methods = [m.value for m in MemoryMode]
```

3. argparse choices（`run_experiment.py:231-234`）：
```python
parser.add_argument(
    "--methods",
    nargs="+",
    choices=[m.value for m in MemoryMode],
    help="Methods to test (default: all four)",
)
```

- [ ] **Step 4: 运行全部测试**

Run: `pytest tests/ -v --ignore=tests/stores`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/main.py app/experiment/runner.py run_experiment.py
git commit -m "refactor: adapt API, experiment runner, and CLI to MemoryMode enum"
```

---

### Task 7: Lint + 全量测试验证

- [ ] **Step 1: 运行 ruff lint**

Run: `ruff check app/ tests/ run_experiment.py`
Expected: 无新增错误

- [ ] **Step 2: 运行 ruff format**

Run: `ruff format --check app/ tests/ run_experiment.py`
Expected: 无格式问题

- [ ] **Step 3: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: 最终 Commit（如有 lint fix）**

```bash
git add -A
git commit -m "chore: lint fixes for memory mode refactor"
```
