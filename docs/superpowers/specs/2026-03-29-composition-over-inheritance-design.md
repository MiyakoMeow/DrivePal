# 重构：组合大于继承

## 目标

将项目中所有基于继承的类型定义重构为基于组合的设计，遵循"组合大于继承"原则。修改前后行为完全一致，允许破坏接口向后兼容。

## 变更范围

1. **Provider 配置层** — 消除 `LLMProviderConfig` / `EmbeddingProviderConfig` / `JudgeProviderConfig` 之间的字段重复
2. **MemoryStore 层** — 消除 `BaseMemoryStore` 继承链，拆分为可组合组件 + Protocol
3. **Loader 层** — 消除 `DatasetLoader` 静态分发，改为注册表 + Protocol
4. **调用方适配 + 测试更新**

---

## 1. Provider 配置层

### 现状

三个 dataclass 各自独立定义 `model`、`base_url`、`api_key`：

```
LLMProviderConfig(model, base_url, api_key, temperature)
EmbeddingProviderConfig(model, device, base_url, api_key)
JudgeProviderConfig(model, base_url, api_key, temperature)
```

### 重构

提取 `ProviderConfig` 作为共享核心，各专用配置通过组合持有：

```python
@dataclass
class ProviderConfig:
    model: str
    base_url: str | None = None
    api_key: str | None = None

@dataclass
class LLMProviderConfig:
    provider: ProviderConfig
    temperature: float = 0.7

@dataclass
class EmbeddingProviderConfig:
    provider: ProviderConfig
    device: str = "cpu"

@dataclass
class JudgeProviderConfig:
    provider: ProviderConfig
    temperature: float = 0.1
```

`from_dict()` 工厂方法内部解析后构造嵌套对象，对外接口不变。

### 调用方变更

- `provider.model` → `provider.provider.model`
- `provider.base_url` → `provider.provider.base_url`
- `provider.api_key` → `provider.provider.api_key`

受影响文件：`chat.py`、`embedding.py`、`settings.py`（`get_judge_model()`）、`judge.py`。

---

## 2. MemoryStore 层

### 现状

```
MemoryStore (ABC) → BaseMemoryStore (ABC) → 4个子类
```

`BaseMemoryStore` 承担过多职责：事件存储、关键词搜索、反馈管理、交互写入。

### 重构

#### 2a. MemoryStore → Protocol

`interfaces.py` 中的 `MemoryStore` 从 ABC 改为 `typing.Protocol`，声明所有方法签名（不再有 `NotImplementedError`）：

```python
class MemoryStore(Protocol):
    store_name: str
    requires_embedding: bool
    requires_chat: bool
    supports_interaction: bool
    def write(self, event: MemoryEvent) -> str: ...
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str: ...
```

#### 2b. 可组合组件（`components.py`）

从 `BaseMemoryStore` 和 `MemoryBankStore` 中提取：

| 组件 | 职责 | 来源 |
|------|------|------|
| `EventStorage` | events.json CRUD + ID生成 | BaseMemoryStore.__init__, _generate_id, write, events_store |
| `KeywordSearch` | 关键词搜索 | BaseMemoryStore._keyword_search, search |
| `FeedbackManager` | 反馈更新 + 策略权重 | BaseMemoryStore.update_feedback, _update_strategy |
| `SimpleInteractionWriter` | 简单交互写入 | BaseMemoryStore.write_interaction |
| `MemoryBankEngine` | 遗忘曲线 + 聚合 + 摘要 | MemoryBankStore 全部独有逻辑 |

#### 2c. Store 变为薄组合层

每个 Store 通过组合所需组件实现 `MemoryStore` Protocol：

- **KeywordMemoryStore** — EventStorage + KeywordSearch + FeedbackManager + SimpleInteractionWriter
- **LLMOnlyMemoryStore** — EventStorage + LLM搜索逻辑 + FeedbackManager + SimpleInteractionWriter
- **EmbeddingMemoryStore** — EventStorage + 向量搜索 + KeywordSearch(fallback) + FeedbackManager + SimpleInteractionWriter
- **MemoryBankStore** — EventStorage + MemoryBankEngine + FeedbackManager

#### 2d. 属性兼容

为测试中直接访问 `store.events_store` / `store.strategies_store` 提供属性代理：

```python
@property
def events_store(self) -> JSONStore:
    return self._storage._store
```

#### 2e. 文件结构

```
app/memory/
├── components.py       # 新增：5个可组合组件
├── interfaces.py       # Protocol 替代 ABC
├── memory.py           # 不变
├── schemas.py          # 不变
├── types.py            # 不变
├── utils.py            # 不变
└── stores/
    ├── keyword_store.py     # 重写为组合
    ├── llm_store.py         # 重写为组合
    ├── embedding_store.py   # 重写为组合
    └── memory_bank_store.py # 重写为组合
```

---

## 3. Loader 层

### 现状

`DatasetLoader` 使用静态方法 + if/elif 分发。两个 Loader 没有共同接口约束。

### 重构

#### 3a. DatasetLoader Protocol

```python
# app/experiment/loaders/base.py
class DatasetLoader(Protocol):
    def load(self) -> Dataset: ...
    def get_test_cases(self) -> list[dict]: ...
```

#### 3b. 注册表

```python
# app/experiment/loaders/__init__.py
_LOADERS: dict[str, type[DatasetLoader]] = {
    "sgd_calendar": SGDCalendarLoader,
    "scheduler": SchedulerLoader,
}

def get_test_cases(dataset: str) -> list[dict]:
    if dataset not in _LOADERS:
        raise ValueError(f"Unknown dataset: {dataset}")
    return _LOADERS[dataset]().get_test_cases()
```

#### 3c. 调用方

`prepare.py` 的 `_load_dataset` 改为使用 `loaders.get_test_cases()`。

---

## 4. 测试变更

| 测试文件 | 变更内容 |
|----------|----------|
| `test_settings.py` | `p.model` → `p.provider.model`；构造方式变更 |
| `test_memory_store_contract.py` | `store.events_store` / `store.strategies_store` → 属性代理 |
| `test_memory_bank.py` | 同上 |
| `test_keyword_store.py` | `store.strategies_store` → 属性代理 |
| `test_storage.py` | 同上 |
| `test_judge.py` | `judge_model.providers[0].model` → `.provider.model` |
| 其他测试 | 通过 MemoryModule Facade 调用，接口不变 |

---

## 约束

- 修改前后行为完全一致
- 可以破坏接口向后兼容
- 全过程在 `split-memory` 分支上进行

## 未解决问题

无。
