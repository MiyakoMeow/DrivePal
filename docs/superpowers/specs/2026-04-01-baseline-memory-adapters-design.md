# 基线记忆后端适配器设计

## 目标

将 VehicleMemBench 中的 4 个基线记忆形式（none/gold/summary/kv）封装为与 `MemoryBankAdapter` 同级的 adapter，注册到 `ADAPTERS` 字典，供 `runner.py` 统一调用。不修改子模块内容。

## 约束

- **仅评估用途**：这些 adapter 仅在 benchmark 评估中使用，不用于生产 API。
- **不修改子模块**：VehicleMemBench 代码不做任何修改。
- **不修改 `app/memory/`**：生产记忆系统代码不受影响。
- **排除 lightmem**：依赖外部模块和 LLMLingua-2 模型。
- **复用 ChatModel**：summary/kv 构建时复用项目已有的 ChatModel 配置（通过 `agent_client` 参数传入）。
- **保持评估方法论**：run 阶段的评估方式必须与 VMB 原始实现一致，不改变评估结果。

## 生产 vs 评估区分

通过目录层级区分：
- 生产后端：`app/memory/stores/`（如 `MemoryBankStore`）
- 评估后端：`adapters/memory_adapters/`（如 `MemoryBankAdapter` 及本次新增的基线 adapter）

## 核心抽象

### BaselineMemory

位于 `adapters/memory_adapters/common.py`，作为基线 adapter 的统一返回类型。使用 dataclass。

```python
@dataclass
class BaselineMemory:
    """基线记忆的轻量容器。"""
    memory_type: str          # "none" | "gold" | "summary" | "kv"
    memory_text: str          # summary 文本，none/gold 为空
    kv_store: dict[str, str]  # kv 字典，非 kv 为空 dict
```

注意：`BaselineMemory` 不内嵌 `search()` 方法。搜索行为由 adapter 和 runner 协作处理——不同基线类型的评估方式完全不同（见 run 阶段设计）。

### Adapter 接口

所有 adapter（包括 MemoryBankAdapter）统一接口：

```python
class XxxAdapter:
    TAG: str  # 唯一标识符

    def __init__(self, data_dir: Path): ...

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        """构建记忆，返回 BaselineMemory。基线 adapter 通过 **kwargs 接收可选参数。"""

    def get_search_client(self, store) -> StoreClient:
        """返回搜索客户端。仅 memory_bank 类型使用。"""
```

`MemoryBankAdapter.add()` 签名更新为 `add(self, history_text: str, **kwargs)` 以兼容统一调用。`**kwargs` 被忽略。

## 四个基线 Adapter

### NoneAdapter

- **文件**: `adapters/memory_adapters/none_adapter.py`
- **TAG**: `"none"`
- **add()**: 返回空 `BaselineMemory(memory_type="none")`。忽略所有 kwargs。
- **无外部依赖**
- **评估行为**: run 阶段不注入任何记忆上下文，不提供 memory_search 工具。LLM 仅凭 system prompt 回答。

### GoldAdapter

- **文件**: `adapters/memory_adapters/gold_adapter.py`
- **TAG**: `"gold"`
- **add()**: 返回空 `BaselineMemory(memory_type="gold")`。gold memory 是每个 event 独立的，无法在文件级 prepare 阶段获取。
- **无外部依赖**
- **评估行为**: run 阶段在 event 循环内取 `event.get("gold_memory", "")`，调用 VMB 的 `process_task_direct()` 注入到 system prompt。保持与原始实现完全一致。

### SummaryAdapter

- **文件**: `adapters/memory_adapters/summary_adapter.py`
- **TAG**: `"summary"`
- **add()**: 调用 VMB 的 `split_history_by_day()` + `build_memory_recursive_summary(agent_client, daily)`，将结果存入 `memory_text`。需要 `**kwargs` 中传入 `agent_client`。
- **依赖**: 需要 `agent_client`（LLM 调用）
- **评估行为**: run 阶段调用 VMB 的 `process_task_with_memory()`，将 summary 文本注入 system prompt。不提供 memory_search 工具。保持与原始实现完全一致。

### KVAdapter

- **文件**: `adapters/memory_adapters/kv_adapter.py`
- **TAG**: `"kv"`
- **add()**: 调用 VMB 的 `split_history_by_day()` + `build_memory_key_value(agent_client, daily)`，将 `MemoryStore.to_dict()` 存入 `kv_store`。需要 `**kwargs` 中传入 `agent_client`。
- **依赖**: 需要 `agent_client`（LLM 调用）
- **评估行为**: run 阶段从 `kv_store` 恢复 `VMBMemoryStore` 实例，调用 VMB 的 `process_task_with_kv_memory()`，提供 `memory_search` + `memory_list` 工具。保持与原始实现完全一致。

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

`runner.py` 中 `SUPPORTED_MEMORY_TYPES` 同步更新为 `{"none", "gold", "summary", "kv", "memory_bank"}`。

## runner.py 改造

### 设计原则

prepare 阶段可以统一走 adapter 路径，但 run 阶段必须按类型分发——因为 VMB 对不同基线使用完全不同的评估函数，不能统一为一个 `_run_baseline_eval`。

### prepare 阶段

`_prepare_single()` 统一走 `ADAPTERS` 路径：

```python
def _prepare_single(agent_client, history_text, file_num, memory_type):
    adapter_cls = ADAPTERS[memory_type]
    adapter = adapter_cls(data_dir=_get_output_dir() / f"store_{memory_type}_{file_num}")
    store = adapter.add(history_text, agent_client=agent_client)
    if isinstance(store, BaselineMemory):
        return {
            "type": store.memory_type,
            "memory_text": store.memory_text,
            "kv_store": store.kv_store,
        }
    return {"type": memory_type, "data_dir": str(adapter.data_dir)}
```

### run 阶段

`_run_single()` 保持按 memory_type 分发，但使用 VMB 原始评估函数：

```python
def _run_single(agent_client, events, history_text, prep_data, file_num, memory_type, reflect_num):
    results = []
    for i, event in enumerate(events):
        query = event.get("query", "")
        reasoning_type = event.get("reasoning_type", "")
        ref_calls = parse_answer_to_tools(event.get("new_answer", []))
        gold_memory = event.get("gold_memory", "")
        task = {"query": query, "tools": ref_calls, "reasoning_type": reasoning_type}

        try:
            if memory_type == "none":
                result = process_task_direct(task, i, agent_client, reflect_num)
            elif memory_type == "gold":
                task["history_text"] = gold_memory
                result = process_task_direct(task, i, agent_client, reflect_num)
            elif memory_type == "summary":
                memory_text = prep_data.get("memory_text", "")
                result = process_task_with_memory(task, i, memory_text, agent_client, reflect_num)
            elif memory_type == "kv":
                vmb_store = VMBMemoryStore()
                vmb_store.store = prep_data.get("kv_store", {})
                result = process_task_with_kv_memory(task, i, vmb_store, agent_client, reflect_num)
            elif memory_type in ADAPTERS:
                result = _run_custom_adapter(agent_client, task, i, prep_data, memory_type, reflect_num)
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
```

与当前 runner.py 的区别：
1. `none` 分支新增：调用 `process_task_direct()` 但不注入 history_text
2. 逻辑顺序调整：先检查基线类型（none/gold/summary/kv），再 fallback 到 ADAPTERS
3. gold memory 从 event 内获取（保持原始行为）

### prepare 阶段的统一性

prepare 阶段是本次改造的重点——所有类型统一走 `ADAPTERS` 路径，消除了 prepare 中的 `if/elif` 分支。run 阶段的分支保留是因为评估方法论的差异是本质的，不应被掩盖。

## BaselineMemory 序列化/反序列化

prepare 阶段产出的 JSON：

```json
{
  "type": "summary",
  "memory_text": "...",
  "kv_store": {}
}
```

run 阶段直接从 `prep_data` 读取字段，无需反序列化为 `BaselineMemory` 对象。`BaselineMemory` 仅在 prepare 阶段作为 adapter 的返回值使用。

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `adapters/memory_adapters/common.py` | 修改：新增 `BaselineMemory` dataclass |
| `adapters/memory_adapters/none_adapter.py` | 新增 |
| `adapters/memory_adapters/gold_adapter.py` | 新增 |
| `adapters/memory_adapters/summary_adapter.py` | 新增 |
| `adapters/memory_adapters/kv_adapter.py` | 新增 |
| `adapters/memory_adapters/__init__.py` | 修改：注册 4 个新 adapter |
| `adapters/memory_adapters/memory_bank_adapter.py` | 修改：`add()` 签名更新为 `add(self, history_text, **kwargs)` |
| `adapters/runner.py` | 修改：prepare 统一走 ADAPTERS，run 新增 none 分支，更新 SUPPORTED_MEMORY_TYPES |
| `tests/` | 新增：基线 adapter 测试 |

## 不变的文件

- `vendor/VehicleMemBench/` — 子模块不修改
- `app/memory/` — 生产记忆系统不修改
- `app/agents/` — Agent 工作流不修改
- `app/api/` — API 层不修改
