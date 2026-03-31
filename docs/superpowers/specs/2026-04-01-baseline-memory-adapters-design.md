# 基线记忆后端适配器 + 生产 Store 设计

## 目标

1. 将 VehicleMemBench 的 4 个基线（none/gold/summary/kv）封装为评估用 adapter，注册到 `ADAPTERS`，简化 runner.py。
2. 将 summary 和 KV 封装为生产用 store，注册到 `_STORES_REGISTRY`，接入 FastAPI API。

不修改子模块内容。

## 约束

- **不修改子模块**：VehicleMemBench 代码不做任何修改。
- **不修改 `app/memory/` 现有代码**：MemoryBankStore、MemoryModule、components 等不受影响。
- **排除 lightmem**：依赖外部模块和 LLMLingua-2 模型。
- **复用 VMB 实现**：评估 adapter 直接调用 VMB 函数。生产 store 复用 VMB 的 prompt 和工具 schema。
- **保持评估方法论**：run 阶段的评估方式与 VMB 原始实现一致，不改变评估结果。
- **实时增量更新**：生产 store 的 write() 累积事件后按阈值触发 LLM 提取（与 MemoryBankEngine 模式一致）。

## 生产 vs 评估区分

通过目录层级区分：
- 生产后端：`app/memory/stores/`（如 `MemoryBankStore`、新增 `SummaryStore`、`KVStore`）
- 评估后端：`adapters/memory_adapters/`（如 `MemoryBankAdapter` 及基线 adapter）

## 第一部分：评估层 Adapter

### BaselineMemory

位于 `adapters/memory_adapters/common.py`，使用 dataclass。

```python
@dataclass
class BaselineMemory:
    memory_type: str          # "none" | "gold" | "summary" | "kv"
    memory_text: str          # summary 文本，none/gold 为空
    kv_store: dict[str, str]  # kv 字典，非 kv 为空 dict
```

### 四个基线 Adapter

| Adapter | 文件 | add() 行为 | 依赖 |
|---------|------|-----------|------|
| NoneAdapter | `none_adapter.py` | 返回空 BaselineMemory | 无 |
| GoldAdapter | `gold_adapter.py` | 返回空 BaselineMemory（gold memory 在 run 阶段从 event 获取） | 无 |
| SummaryAdapter | `summary_adapter.py` | 调用 `build_memory_recursive_summary()` | agent_client |
| KVAdapter | `kv_adapter.py` | 调用 `build_memory_key_value()` | agent_client |

统一接口：

```python
class XxxAdapter:
    TAG: str
    def __init__(self, data_dir: Path): ...
    def add(self, history_text: str, **kwargs) -> BaselineMemory: ...
    def get_search_client(self, store) -> StoreClient: ...
```

### runner.py 改造

**prepare 阶段**：所有类型统一走 `ADAPTERS` 路径，消除 `if/elif`。

**run 阶段**：保持按类型分发（VMB 对不同基线使用不同评估函数，这是本质差异）：
- none → `process_task_direct()`（无 history_text）
- gold → `process_task_direct()`（注入 event 级 gold_memory）
- summary → `process_task_with_memory()`
- kv → `process_task_with_kv_memory()`
- memory_bank → `_run_custom_adapter()`

### 兼容性注意

kv 的 prepared data JSON key 从 `"store"` 改为 `"kv_store"`。已有的 `kv_file_*.json` 需删除后重新 prepare。

`SUPPORTED_MEMORY_TYPES` 更新为 `{"none", "gold", "summary", "kv", "memory_bank"}`。

## 第二部分：生产层 Store

### 前置变更：ChatModel.generate_with_tools()

在 `app/models/chat.py` 的 `ChatModel` 上新增方法：

```python
def generate_with_tools(
    self,
    prompt: str,
    tools: list[dict],
    system_prompt: str | None = None,
    *,
    max_rounds: int = 10,
    tool_executor: Callable[[str, dict], str],
) -> str:
    """带工具调用的生成，支持多轮 tool calling loop。"""
```

**行为：**
1. 用 `_create_client()` 创建 `ChatOpenAI`，调用 `bind_tools(tools)`
2. 构造 messages，invoke 得到 `AIMessage`
3. 多轮循环：`AIMessage.tool_calls` → `ToolMessage` → 再次 invoke，直到无 tool_calls 或达到 max_rounds
4. 多 provider fallback：某 provider 失败后尝试下一个

### MemoryMode 扩展

`app/memory/types.py` 新增：

```python
class MemoryMode(StrEnum):
    MEMORY_BANK = "memory_bank"
    SUMMARY = "summary"
    KEY_VALUE = "key_value"
```

### SummaryStore

**文件**：`app/memory/stores/summary_store.py`

**Protocol 属性**：
- `store_name = "summary"`
- `requires_embedding = False`
- `requires_chat = True`
- `supports_interaction = False`

**内部状态**（持久化到 JSON 文件）：
- `summary: str` — 当前累积摘要文本
- `events: list[MemoryEvent]` — 原始事件日志

**write(event)**：
1. 将 event 追加到事件日志
2. 累积未处理事件计数
3. 达到阈值后触发 `_update_summary()`：
   - 复用 VMB 的 system prompt（`model_evaluation.py:468-497`，偏好提取规则）
   - 复用 VMB 的 `memory_update` 工具 schema（`model_evaluation.py:427-449`）
   - 调用 `ChatModel.generate_with_tools()`，传入当前 summary + 未处理事件内容
   - LLM 调用 `memory_update(new_memory)` 替换摘要
   - 复用 VMB 的后处理（8192 字符截断、JSON regex fallback）
4. 持久化更新后的 summary

**search(query, top_k)**：
- 返回 `[SearchResult(event={"content": self.summary, "type": "summary"}, score=1.0, source="summary")]`
- summary 为空时返回 `[]`

**get_history(limit)**：
- 从事件日志返回最近 N 个事件

**update_feedback(event_id, feedback)**：
- 记录反馈元数据（有限用途，summary 是单一文本块，无法定向修改）

**write_interaction(query, response, event_type)**：
- 记录为事件，纳入下次 summary 更新

### KVStore

**文件**：`app/memory/stores/kv_store.py`

**Protocol 属性**：
- `store_name = "key_value"`
- `requires_embedding = False`
- `requires_chat = True`
- `supports_interaction = True`

**内部状态**（持久化到 JSON 文件）：
- `kv_data: dict[str, str]` — KV 存储（复用 VMB `MemoryStore` 的数据结构）
- `events: list[MemoryEvent]` — 原始事件日志

**write(event)**：
1. 将 event 追加到事件日志
2. 累积未处理事件计数
3. 达到阈值后触发 `_extract_kv()`：
   - 复用 VMB 的 system prompt（`model_evaluation.py:665-695`）
   - 复用 VMB 的 `memory_add`、`memory_remove` 工具 schema
   - 调用 `ChatModel.generate_with_tools()`，传入当前 KV keys + 未处理事件内容
   - LLM 调用 `memory_add`/`memory_remove` 更新 KV 存储
   - 直接修改内部的 `kv_data` 字典
4. 持久化更新后的 kv_data

**search(query, top_k)**：
- 复用 VMB `MemoryStore.memory_search()` 的模糊匹配逻辑（精确匹配 + 子串匹配）
- 每个匹配的 KV 对转化为 `SearchResult(event={"content": f"{key}: {value}", "type": "kv_entry"}, score=score, source="kv_store")`

**get_history(limit)**：
- 从事件日志返回最近 N 个事件

**update_feedback(event_id, feedback)**：
- feedback.action == "ignore" → 可触发相关 KV 条目的删除
- 记录反馈元数据

**write_interaction(query, response, event_type)**：
- 记录为事件，纳入下次 KV 提取

### 批量更新阈值

与 MemoryBankEngine 模式一致：
- summary：累积 2 个未处理事件后触发更新
- kv：累积 2 个未处理事件后触发更新

### _STORES_REGISTRY 注册

`app/memory/memory.py` 的 `_import_all_stores()` 新增：

```python
from app.memory.stores.summary_store import SummaryStore
from app.memory.stores.kv_store import KVStore
register_store(MemoryMode.SUMMARY, SummaryStore)
register_store(MemoryMode.KEY_VALUE, KVStore)
```

## 第三部分：文件变更清单

### 评估层

| 文件 | 操作 |
|------|------|
| `adapters/memory_adapters/common.py` | 修改：新增 `BaselineMemory` dataclass |
| `adapters/memory_adapters/none_adapter.py` | 新增 |
| `adapters/memory_adapters/gold_adapter.py` | 新增 |
| `adapters/memory_adapters/summary_adapter.py` | 新增 |
| `adapters/memory_adapters/kv_adapter.py` | 新增 |
| `adapters/memory_adapters/__init__.py` | 修改：注册 4 个新 adapter |
| `adapters/memory_adapters/memory_bank_adapter.py` | 修改：`add()` 签名更新为 `add(self, history_text, **kwargs)` |
| `adapters/runner.py` | 修改：prepare 统一走 ADAPTERS，run 新增 none 分支 |

### 生产层

| 文件 | 操作 |
|------|------|
| `app/models/chat.py` | 修改：新增 `generate_with_tools()` 方法 |
| `app/memory/types.py` | 修改：MemoryMode 新增 SUMMARY、KEY_VALUE |
| `app/memory/memory.py` | 修改：`_import_all_stores()` 注册新 store |
| `app/memory/stores/summary_store.py` | 新增 |
| `app/memory/stores/kv_store.py` | 新增 |

### 测试

| 文件 | 操作 |
|------|------|
| `tests/stores/test_summary_store.py` | 新增 |
| `tests/stores/test_kv_store.py` | 新增 |
| `tests/test_memory_store_contract.py` | 修改：新增 summary/kv 的 contract 测试 |

## 不变的文件

- `vendor/VehicleMemBench/` — 子模块不修改
- `app/memory/interfaces.py` — Protocol 不变
- `app/memory/schemas.py` — 数据模型不变
- `app/memory/components.py` — MemoryBankEngine 不变
- `app/memory/stores/memory_bank_store.py` — 现有 store 不变
- `app/agents/` — Agent 工作流不变
- `app/api/` — API 层不变（MemoryModule facade 自动支持新模式）
