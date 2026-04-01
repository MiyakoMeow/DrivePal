# 记忆后端隔离重构设计

## 背景

当前 `app/memory/components.py` 混合了通用组件和 MemoryBank 专属逻辑，共 761 行。后续需要添加其它记忆后端，现有结构无法清晰区分复用层与专属层。

## 目标

- 将 MemoryBank 专属逻辑从 `components.py` 移至 `stores/memory_bank/` 目录
- `components.py` 仅保留通用可复用组件
- 新增记忆后端只需在 `stores/` 下新建目录，实现 `MemoryStore` Protocol

## 目录结构

```
app/memory/
├── interfaces.py              # MemoryStore Protocol（不变）
├── schemas.py                 # 通用数据模型（不变）
├── types.py                   # MemoryMode 枚举（不变）
├── utils.py                   # forgetting_curve, cosine_similarity（不变）
├── memory.py                  # MemoryModule Facade（不变）
├── components.py              # 仅保留通用组件
├── stores/
│   ├── memory_bank/
│   │   ├── __init__.py        # 导出 MemoryBankStore
│   │   ├── store.py           # MemoryBankStore 薄适配层
│   │   ├── engine.py          # MemoryBankEngine 核心 write/search/interaction
│   │   ├── personality.py     # PersonalityManager
│   │   └── summarization.py   # SummaryManager
│   └── __init__.py
```

## 组件划分

### components.py（通用层，所有后端可复用）

保留以下类，不做任何逻辑改动：

| 类 | 职责 |
|---|---|
| `EventStorage` | 事件 JSON 文件 CRUD + ID 生成 |
| `KeywordSearch` | 关键词大小写不敏感搜索 |
| `FeedbackManager` | 反馈更新 + 策略权重管理 |
| `SimpleInteractionWriter` | 简单交互写入 |

移除所有 MemoryBank 专属常量：
- `PERSONALITY_SUMMARY_THRESHOLD`, `OVERALL_PERSONALITY_THRESHOLD`
- `SOFT_FORGET_THRESHOLD`, `SOFT_FORGET_STRENGTH`

### stores/memory_bank/engine.py

`MemoryBankEngine` 类，从 `components.py` 搬入。保留以下职责：
- `write()` / `search()` 核心流程
- `write_interaction()` 核心流程
- `_search_by_keyword()` / `_search_by_embedding()` 事件检索
- `_strengthen_events()` / `_strengthen_interactions()` 记忆强化
- `_soft_forget_events()` 软遗忘
- `_expand_event_interactions()` 交互展开
- `_should_append_to_event()` / `_append_interaction_to_event()` 事件聚合
- `_update_event_summary()` 事件摘要更新

不再直接包含 personality 和 summarization 的实现细节，改为委托给 manager。

常量搬入：
- `AGGREGATION_SIMILARITY_THRESHOLD`, `DAILY_SUMMARY_THRESHOLD`
- `OVERALL_SUMMARY_THRESHOLD`, `SUMMARY_WEIGHT`, `TOP_K`
- `SOFT_FORGET_THRESHOLD`, `SOFT_FORGET_STRENGTH`

### stores/memory_bank/personality.py

`PersonalityManager` 类，封装人格相关逻辑：

```python
class PersonalityManager:
    def __init__(self, data_dir: Path) -> None: ...

    async def search(self, query: str, top_k: int) -> list[SearchResult]: ...
    async def strengthen(self, matched_date_groups: list[str]) -> None: ...
    async def maybe_summarize(self, date_group: str, ...) -> None: ...
    async def generate_overall_text(self, personality_data: dict) -> Optional[str]: ...
```

常量：
- `PERSONALITY_SUMMARY_THRESHOLD`
- `OVERALL_PERSONALITY_THRESHOLD`

### stores/memory_bank/summarization.py

`SummaryManager` 类，封装摘要相关逻辑：

```python
class SummaryManager:
    def __init__(self, data_dir: Path) -> None: ...

    async def search_summaries(self, query: str, daily_summaries: dict, top_k: int) -> list[SearchResult]: ...
    async def strengthen_summaries(self, matched_keys: list[str], daily_summaries: dict) -> None: ...
    async def maybe_summarize(self, date_group: str, events: list[dict], chat_model: ChatModel) -> None: ...
    async def update_overall_summary(self, daily_summaries: dict, chat_model: ChatModel) -> None: ...
```

### stores/memory_bank/store.py

原 `stores/memory_bank_store.py` 搬入，导入路径更新。

### stores/memory_bank/__init__.py

```python
from app.memory.stores.memory_bank.store import MemoryBankStore

__all__ = ["MemoryBankStore"]
```

### memory.py 注册表更新

```python
def _import_all_stores() -> None:
    from app.memory.stores.memory_bank import MemoryBankStore
    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
```

## 引用关系

```
store.py
  ├── engine.py
  │     ├── components.EventStorage
  │     ├── components.KeywordSearch (via search methods)
  │     ├── personality.PersonalityManager
  │     └── summarization.SummaryManager
  └── components.FeedbackManager
```

## 新增后端步骤

1. 在 `stores/` 下新建目录
2. 实现 `MemoryStore` Protocol
3. 在 `types.py` 添加 `MemoryMode` 枚举值
4. 在 `memory.py` 注册

## 测试策略

- 现有测试不变，仅更新导入路径
- `personality.py` 和 `summarization.py` 各自可独立测试

## 未解决问题

- 无
