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

受影响文件：

| 文件 | 具体位置 |
|------|----------|
| `settings.py` | `_build_env_provider()` 构造 LLMProviderConfig |
| `settings.py` | `_build_judge_provider()` 构造 JudgeProviderConfig |
| `settings.py` | `get_judge_model()` 从 JudgeConfig 重建 LLMConfig |
| `settings.py` | `LLMSettings.load()` 去重 key `(p.model, p.base_url)` → `(p.provider.model, p.provider.base_url)` |
| `chat.py` | 所有 `provider.model/base_url/api_key` 访问 |
| `embedding.py` | 所有 `provider.model/base_url/api_key/device` 访问 + fallback 构造 |
| `judge.py` | `judge_model.providers[0].model` |
| `conftest.py` | `provider.base_url` / `provider.api_key` |

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
| `KeywordSearch` | 关键词搜索（纯文本匹配） | BaseMemoryStore._keyword_search, search |
| `FeedbackManager` | 反馈更新 + 策略权重 | BaseMemoryStore.update_feedback, _update_strategy |
| `SimpleInteractionWriter` | 简单交互写入 | BaseMemoryStore.write_interaction |
| `MemoryBankEngine` | 遗忘曲线 + 聚合 + 摘要 + 独立的关键词/向量搜索 | MemoryBankStore 全部独有逻辑 |

注意：`MemoryBankEngine` 内部有自己的搜索逻辑（含遗忘曲线评分），不使用 `KeywordSearch` 组件。`KeywordSearch` 仅用于 Keyword/Embedding/LLM 三个 Store。

#### 2c. Store 变为薄组合层

每个 Store 通过组合所需组件隐式满足 `MemoryStore` Protocol：

- **KeywordMemoryStore** — EventStorage + KeywordSearch + FeedbackManager + SimpleInteractionWriter
- **LLMOnlyMemoryStore** — EventStorage + LLM搜索逻辑 + FeedbackManager + SimpleInteractionWriter
- **EmbeddingMemoryStore** — EventStorage + 向量搜索 + KeywordSearch(fallback) + FeedbackManager + SimpleInteractionWriter
- **MemoryBankStore** — EventStorage + MemoryBankEngine + FeedbackManager

注意：`EmbeddingMemoryStore.search` 的 `min_results` 额外参数保留，Protocol 签名不含此参数（结构化子类型允许额外参数有默认值）。

#### 2d. 属性兼容

为测试中直接访问的 Store 内部属性提供代理：

```python
# 所有 Store 均提供：
@property
def events_store(self) -> JSONStore: return self._storage._store

@property
def strategies_store(self) -> JSONStore: return self._feedback._strategies_store

# MemoryBankStore 额外提供：
@property
def summaries_store(self) -> JSONStore: return self._engine._summaries_store

@property
def interactions_store(self) -> JSONStore: return self._engine._interactions_store
```

#### 2e. memory.py 注册表适配

`memory.py` 标注为"不变"有误，实际需要变更：

- `_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]]` → `dict[MemoryMode, type]`（Protocol 不能用作 `type[X]`）
- `register_store` 参数改为 `store_cls: type`
- `_create_store` 中通过 `getattr(store_cls, 'requires_embedding', False)` 检查能力标记

#### 2f. 文件结构

```
app/memory/
├── components.py       # 新增：5个可组合组件
├── interfaces.py       # Protocol 替代 ABC
├── memory.py           # 注册表类型适配
├── schemas.py          # 不变
├── types.py            # 不变
├── utils.py            # 不变
└── stores/
    ├── __init__.py         # 移除 BaseMemoryStore 导出
    ├── base.py             # 删除
    ├── keyword_store.py     # 重写为组合
    ├── llm_store.py         # 重写为组合
    ├── embedding_store.py   # 重写为组合
    └── memory_bank_store.py # 重写为组合
```

---

## 3. Loader 层

### 现状

`DatasetLoader` 使用静态方法 + if/elif 分发。两个 Loader 没有共同接口约束，所有方法为 `@classmethod`。

### 重构

#### 3a. DatasetLoader Protocol

```python
# app/experiment/loaders/base.py
class DatasetLoader(Protocol):
    def load(self) -> Dataset: ...
    def get_test_cases(self) -> list[dict]: ...
```

#### 3b. Loader 方法改为实例方法

`SGDCalendarLoader` 和 `SchedulerLoader` 的 `@classmethod` 全部改为实例方法。类变量 `_cache` 改为模块级变量：

```python
# sgd_calendar.py
_cache = None

class SGDCalendarLoader:
    def load(self) -> Dataset: ...
    def get_test_cases(self) -> list[dict]: ...
```

#### 3c. 注册表

```python
# app/experiment/loaders/__init__.py
_LOADERS: dict[str, Callable[[], DatasetLoader]] = {
    "sgd_calendar": SGDCalendarLoader,
    "scheduler": SchedulerLoader,
}

def get_test_cases(dataset: str) -> list[dict]:
    if dataset not in _LOADERS:
        raise ValueError(f"Unknown dataset: {dataset}")
    return _LOADERS[dataset]().get_test_cases()
```

#### 3d. 调用方

`prepare.py` 的 `_load_dataset` 改为使用 `loaders.get_test_cases()`，并更新 `@patch` 路径。

---

## 4. 测试变更

| 测试文件 | 变更内容 |
|----------|----------|
| `test_settings.py` | 所有 `p.model` → `p.provider.model`；15+ 处直接构造改为嵌套构造 |
| `test_memory_store_contract.py` | `store.events_store` / `store.strategies_store` → 属性代理 |
| `test_memory_bank.py` | `backend.events_store` / `backend.summaries_store` → 属性代理 |
| `tests/stores/test_keyword_store.py` | `store.strategies_store` → 属性代理 |
| `tests/stores/test_memory_bank_store.py` | `store.interactions_store` → 属性代理 |
| `test_storage.py` | `store.strategies_store` → 属性代理 |
| `test_judge.py` | `judge_model.providers[0].model` → `.provider.model` |
| `test_prepare.py` | `@patch("..._load_dataset")` → 改为 `@patch("...loaders.get_test_cases")` |
| `conftest.py` | `provider.base_url` / `provider.api_key` → `provider.provider.*` |
| 其他测试 | 通过 MemoryModule Facade 调用，接口不变 |

---

## 约束

- 修改前后行为完全一致
- 可以破坏接口向后兼容
- 全过程在 `split-memory` 分支上进行

## 未解决问题

无。
