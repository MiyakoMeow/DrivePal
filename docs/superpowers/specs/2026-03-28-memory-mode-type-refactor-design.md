# Memory Mode 类型深度重构设计

## 目标

消除所有 `memory_mode` 硬编码字符串匹配，Store 类自声明能力，MemoryModule 和 AgentWorkflow 零字符串分支。

## 类型体系

### 新建 `app/memory/types.py`

```python
from enum import StrEnum

class MemoryMode(StrEnum):
    KEYWORD = "keyword"
    LLM_ONLY = "llm_only"
    EMBEDDINGS = "embeddings"
    MEMORY_BANK = "memorybank"
```

使用 `StrEnum`（Python 3.11+），与 `str` 兼容，Pydantic 自动反序列化，LangGraph `TypedDict` 字段保持 `str` 类型不变。

## Store 能力声明

### 修改 `BaseMemoryStore`（`app/memory/stores/base.py`）

新增三个类属性：

```python
requires_embedding: bool = False
requires_chat: bool = False
supports_interaction: bool = False
```

### 各 Store 覆写

| Store | `requires_embedding` | `requires_chat` | `supports_interaction` |
|---|---|---|---|
| `KeywordMemoryStore` | `False` | `False` | `False` |
| `LLMOnlyMemoryStore` | `False` | `True` | `False` |
| `EmbeddingMemoryStore` | `True` | `False` | `False` |
| `MemoryBankStore` | `True` | `True` | `True` |

### 修改 `MemoryStore` 接口（`app/memory/interfaces.py`）

新增 `write_interaction` 抽象方法。`BaseMemoryStore` 默认抛出 `NotImplementedError`，`MemoryBankStore` 覆写为实际实现。消除 `MemoryModule` 中 `hasattr` 检查。

## MemoryModule 重构（`app/memory/memory.py`）

### 注册表

`dict[str, type]` → `dict[MemoryMode, type[MemoryStore]]`

### 构造函数

```python
def __init__(
    self,
    data_dir: str,
    embedding_model: Optional["EmbeddingModel"] = None,
    chat_model: Optional["ChatModel"] = None,
):
```

保持模型参数接口不变，支持外部传入（API 层固定启动时加载）。若未传入，`_create_store` 根据目标 Store 的类属性按需加载。

### 工厂方法

```python
def _create_store(self, mode: MemoryMode) -> MemoryStore:
    store_cls = _STORES_REGISTRY[mode]
    kwargs = {"data_dir": self._data_dir}
    if store_cls.requires_embedding and self._embedding_model is None:
        from app.models.settings import get_embedding_model
        self._embedding_model = get_embedding_model()
    if store_cls.requires_chat and self._chat_model is None:
        from app.models.settings import get_chat_model
        self._chat_model = get_chat_model()
    if store_cls.requires_embedding:
        kwargs["embedding_model"] = self._embedding_model
    if store_cls.requires_chat:
        kwargs["chat_model"] = self._chat_model
    return store_cls(**kwargs)
```

模型实例在首次需要时加载，后续通过 `self._embedding_model` / `self._chat_model` 缓存复用。

### `write_interaction`

移除 `hasattr` 检查，直接调用 `store.write_interaction(...)`。基类默认抛出 `NotImplementedError`。

## AgentWorkflow 简化（`app/agents/workflow.py`）

### 类型签名

```python
def __init__(
    self,
    data_dir: str = "data",
    memory_mode: MemoryMode = MemoryMode.KEYWORD,
    memory_module: Optional[MemoryModule] = None,
):
```

### 消除分支

1. `workflow.py:37-44` — 删除 `if memory_mode in ("embeddings", "memorybank")` 分支，统一 `MemoryModule(data_dir, chat_model=chat_model)`
2. `workflow.py:188-192` — 删除 `if self.memory_mode == "memorybank"` 分支，统一调用 `self.memory_module.write_interaction(user_input, content)`

## 其他改动点

### `app/api/main.py`

- `QueryRequest.memory_mode`: `Literal[...]` → `MemoryMode = MemoryMode.KEYWORD`
- `_ensure_memory_module()`: 保持启动时预加载，传入 `embedding_model` + `chat_model`

### `app/experiment/runner.py`

- `valid_methods = {"keyword", ...}` → `set(MemoryMode)`
- 方法参数类型 `str` → `str | MemoryMode`（兼容 CLI 传入字符串）

### `run_experiment.py`

- argparse `choices` → `[m.value for m in MemoryMode]`
- 默认方法列表 → `[m.value for m in MemoryMode]`

### `app/agents/state.py`

- `memory_mode: str` 保持不变（LangGraph 兼容性）

### `webui/index.html`

- 无需改动（字符串值与 `MemoryMode.value` 一致）

## 测试改动

| 文件 | 改动 |
|---|---|
| `tests/test_chat.py:19,32` | `MemoryModule(str(tmp_path), chat_model=...)` 保持传入 `chat_model` 参数（接口不变） |
| 其他测试 | 无需改动（`StrEnum` 与 `str` 隐式兼容） |

## 涉及文件汇总

| 文件 | 操作 |
|---|---|
| `app/memory/types.py` | 新建 |
| `app/memory/interfaces.py` | 新增 `write_interaction` 抽象方法 |
| `app/memory/stores/base.py` | 新增 3 个类属性 + `write_interaction` 默认实现 |
| `app/memory/stores/llm_store.py` | 新增 `requires_chat = True` |
| `app/memory/stores/embedding_store.py` | 新增 `requires_embedding = True` |
| `app/memory/stores/memory_bank_store.py` | 新增 3 个类属性 + 覆写 `write_interaction` |
| `app/memory/memory.py` | 注册表用 `MemoryMode`，工厂按类属性加载模型 |
| `app/agents/workflow.py` | 类型 + 消除两处字符串分支 |
| `app/api/main.py` | `QueryRequest` 用 `MemoryMode` |
| `app/experiment/runner.py` | `valid_methods` 用 `MemoryMode` |
| `run_experiment.py` | `choices` 用 `MemoryMode` |
