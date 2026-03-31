# 基线记忆后端适配器设计

## 目标

将 VehicleMemBench 中的 4 个基线记忆形式（none/gold/summary/kv）封装为与 `MemoryBankAdapter` 同级的 adapter，注册到 `ADAPTERS` 字典，供 `runner.py` 统一调用。不修改子模块内容。

## 约束

- **仅评估用途**：这些 adapter 仅在 benchmark 评估中使用，不用于生产 API。
- **不修改子模块**：VehicleMemBench 代码不做任何修改。
- **不修改 `app/memory/`**：生产记忆系统代码不受影响。
- **排除 lightmem**：依赖外部模块和 LLMLingua-2 模型。
- **复用 ChatModel**：summary/kv 构建时复用项目已有的 ChatModel 配置（通过 `agent_client` 参数传入）。

## 生产 vs 评估区分

通过目录层级区分：
- 生产后端：`app/memory/stores/`（如 `MemoryBankStore`）
- 评估后端：`adapters/memory_adapters/`（如 `MemoryBankAdapter` 及本次新增的基线 adapter）

## 核心抽象

### BaselineMemory

位于 `adapters/memory_adapters/common.py`，作为所有基线 adapter 的统一返回类型。

```python
class BaselineMemory:
    """基线记忆的轻量容器。"""
    memory_type: str          # "none" | "gold" | "summary" | "kv"
    memory_text: str          # summary/gold 文本，none 为空
    kv_store: dict[str, str]  # kv 字典，非 kv 为空 dict

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """按类型分发搜索。"""
        # none: 返回 []
        # gold/summary: 全量返回 memory_text
        # kv: 委托 VMBMemoryStore.memory_search()
```

### Adapter 接口

每个 adapter 遵循与 `MemoryBankAdapter` 相同的接口模式：

```python
class XxxAdapter:
    TAG: str  # 唯一标识符

    def __init__(self, data_dir: Path): ...

    def add(self, history_text: str, *, agent_client=None, gold_memory="") -> BaselineMemory:
        """构建记忆，返回 BaselineMemory。"""

    def get_search_client(self, store: BaselineMemory) -> StoreClient:
        """返回搜索客户端。"""
```

## 四个基线 Adapter

### NoneAdapter

- **文件**: `adapters/memory_adapters/none_adapter.py`
- **TAG**: `"none"`
- **add()**: 返回空 `BaselineMemory(memory_type="none")`
- **search()**: 返回 `[]`
- **无外部依赖**

### GoldAdapter

- **文件**: `adapters/memory_adapters/gold_adapter.py`
- **TAG**: `"gold"`
- **add()**: 从 `gold_memory` 关键字参数获取 QA 样本的标注文本，存入 `memory_text`
- **search()**: 全量返回 `memory_text`（单个 `SearchResult`，score=1.0）
- **无外部依赖**（无需 LLM 调用）

### SummaryAdapter

- **文件**: `adapters/memory_adapters/summary_adapter.py`
- **TAG**: `"summary"`
- **add()**: 调用 VMB 的 `split_history_by_day()` + `build_memory_recursive_summary(agent_client, daily)`，将结果存入 `memory_text`
- **search()**: 全量返回摘要文本
- **依赖**: 需要 `agent_client`（LLM 调用）

### KVAdapter

- **文件**: `adapters/memory_adapters/kv_adapter.py`
- **TAG**: `"kv"`
- **add()**: 调用 VMB 的 `split_history_by_day()` + `build_memory_key_value(agent_client, daily)`，将 `MemoryStore.to_dict()` 存入 `kv_store`
- **search()**: 内部构造 `VMBMemoryStore`，调用其 `memory_search()` 方法（精确匹配 + 模糊子串匹配）
- **依赖**: 需要 `agent_client`（LLM 调用）

## ADAPTERS 注册

`adapters/memory_adapters/__init__.py`：

```python
ADAPTERS = {
    "memory_bank": MemoryBankAdapter,
    "none": NoneAdapter,
    "gold": GoldAdapter,
    "summary": SummaryAdapter,
    "kv": KVAdapter,
}
```

## runner.py 改造

### prepare 阶段

`_prepare_single()` 简化为：

```python
def _prepare_single(agent_client, history_text, file_num, memory_type):
    adapter_cls = ADAPTERS[memory_type]
    adapter = adapter_cls(data_dir=...)
    store = adapter.add(
        history_text,
        agent_client=agent_client,
        gold_memory=qa_data_gold_memory if memory_type == "gold" else "",
    )
    if isinstance(store, BaselineMemory):
        return {
            "type": memory_type,
            "memory_text": store.memory_text,
            "kv_store": store.kv_store,
        }
    else:
        return {"type": memory_type, "data_dir": str(data_dir)}
```

### run 阶段

`_run_single()` 统一为一条路径：

```python
# 所有类型统一走 ADAPTERS 路径
adapter_cls = ADAPTERS[memory_type]
if isinstance prep_data 中有 "data_dir":
    # custom adapter (memory_bank)
    result = _run_custom_adapter(...)
else:
    # baseline: 从 prep_data 恢复 BaselineMemory
    store = BaselineMemory(memory_type, memory_text, kv_store)
    client = adapter.get_search_client(store)
    result = _run_baseline_eval(agent_client, task, i, client, memory_type, reflect_num)
```

### _run_baseline_eval

新增辅助函数，复用 `_run_custom_adapter` 的大部分逻辑（system_instruction、initial_tools、memory_search 闭包），但搜索委托给 `BaselineMemory.search()`。

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `adapters/memory_adapters/common.py` | 修改：新增 `BaselineMemory` 类 |
| `adapters/memory_adapters/none_adapter.py` | 新增 |
| `adapters/memory_adapters/gold_adapter.py` | 新增 |
| `adapters/memory_adapters/summary_adapter.py` | 新增 |
| `adapters/memory_adapters/kv_adapter.py` | 新增 |
| `adapters/memory_adapters/__init__.py` | 修改：注册 4 个新 adapter |
| `adapters/runner.py` | 修改：简化 prepare/run 逻辑 |
| `tests/` | 新增：基线 adapter 测试 |

## 不变的文件

- `vendor/VehicleMemBench/` — 子模块不修改
- `app/memory/` — 生产记忆系统不修改
- `app/agents/` — Agent 工作流不修改
- `app/api/` — API 层不修改
