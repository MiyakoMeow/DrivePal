# MemoryBank 阶段一：核心架构改造

> 状态：待审查 | 日期：2026-05-09

## 背景

经 DrivePal 与 VehicleMemBench 两方 MemoryBank 实现逐项对比，确认算法层高度对齐（Ebbinghaus 遗忘、四阶段检索、P90 自适应分块、说话人降权等），工程层存五类差异。本文档涵盖阶段一：核心架构改造。

## 目标

1. 完整多用户隔离
2. 错误处理体系统一
3. 配置全量集中
4. 索引损坏恢复降级

不保证向后兼容。

---

## 一、多用户隔离

### 策略：构造时绑定用户，消灭所有 `user_id` 参数

**核心洞察**：`FaissIndex` 已是单用户单元——构造时收 `data_dir`，内部 `_index`/`_metadata`/`_extra` 不感知多用户。当前代码本无 `user_id` 参数。多用户隔离只需在 `MemoryModule` 层加注册表，**下层零改动**。

### 架构

```
MemoryModule (facade, +store_registry)
  └─ _stores: dict[str, MemoryBankStore]   # 新增
       └─ get_store(user_id) → MemoryBankStore
            └─ FaissIndex(f"{data_dir}/user_{user_id}/")  # 子目录隔离
            └─ RetrievalPipeline  (不变, 无 user_id)
            └─ MemoryLifecycle    (不变, 无 user_id)
            └─ Summarizer         (不变, 无 user_id)
            └─ ForgettingCurve    (不变, 无 user_id)
            └─ LlmClient          (不变, 无 user_id)
            └─ BackgroundTaskRunner (每 store 独立)
```

### 变更清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `app/memory/memory.py` | 加 `_stores: dict[str, MemoryBankStore]` + `get_store(user_id)` | 懒初始化注册表 |
| `app/memory/stores/memory_bank/store.py` | `__init__` 收 `user_id` 参数，拼 `user_dir` | `FaissIndex(user_dir, ...)` |
| `app/api/resolvers/mutation.py` | 调用处传 `user_id`（从 GraphQL context 取） | 按需 |
| 其他所有文件 | **零改动** | FaissIndex / RetrievalPipeline / MemoryLifecycle / Summarizer 签名均不变 |

### FaissIndex 零改动证明

```python
# 旧（当前）—— 单用户，data_dir 写死
self._index = FaissIndex(data_dir, config.embedding_dim)

# 新 —— 每用户独立子目录，其余不变
user_dir = data_dir / f"user_{user_id}"
self._index = FaissIndex(user_dir, config.embedding_dim)
#                                             ↑ 完全相同的构造签名
```

### MemoryModule 薄注册表

```python
class MemoryModule:
    _stores: dict[str, MemoryBankStore] = {}

    def get_store(self, user_id: str = "default") -> MemoryBankStore:
        if user_id not in self._stores:
            self._stores[user_id] = MemoryBankStore(
                user_id=user_id,
                data_dir=self._data_dir / "memorybank",
                embedding_model=self._embedding_model,
                chat_model=self._chat_model,
            )
        return self._stores[user_id]

    async def close(self) -> None:
        for store in self._stores.values():
            await store.close()
        self._stores.clear()
```

### MemoryStore Protocol：追加 `close()` 方法

```python
class MemoryStore(Protocol):
    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    async def get_event_type(self, event_id: str) -> str | None: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    async def write_interaction(self, query: str, response: str, event_type: str = "reminder", **kwargs: object) -> InteractionResult: ...
    async def close(self) -> None: ...   # 新增——优雅关闭（释放连接、取消后台任务、持久化）
```

### 权衡

- **优**：FaissIndex / 检索管道 / 摘要器零改动；测试天然隔离（一个 store 实例 = 一个用户）；每用户独立 BackgroundTaskRunner 无并发竞争
- **劣**：用户数增长 → store 实例膨胀。但车载场景用户数有限（家庭用车 ≤ 6 人），可接受
- **弃案**：每方法传 `user_id` → 污染 6 个组件 20+ 方法签名，且 `MemoryStore` Protocol 需改。不选

---

## 二、错误处理体系

### 异常层次

```python
# app/memory/exceptions.py（新增）

class MemoryBankError(Exception):
    """MemoryBank 异常基类。"""

class TransientError(MemoryBankError):
    """可重试的瞬态错误（网络、超时、限速）。"""
    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after

class FatalError(MemoryBankError):
    """不可恢复的永久错误（配置、数据损坏）。"""

class LLMCallFailed(TransientError):
    """LLM 调用失败（可重试）。"""

class EmbeddingFailed(TransientError):
    """嵌入 API 调用失败（可重试）。"""

class SummarizationEmpty(MemoryBankError):
    """LLM 返回空结果——非错误，哨兵信号。"""

class ConfigError(FatalError):
    """配置错误（缺失必要参数、值非法）。"""

class MetadataCorrupted(FatalError):
    """元数据损坏，不可自动恢复。"""

class IndexIntegrityError(FatalError):
    """FAISS 索引文件损坏，不可读取。"""
```

### 各组件改造原则

| 组件 | 当前 | 改为 |
|------|------|------|
| `LlmClient.call()` | 返回 `str \| None`（`None`=失败，`""`=空结果） | 返回 `str`（非空）。抛 `LLMCallFailed`（API 失败）或 `SummarizationEmpty`（空内容哨兵异常）。调用方统一 try/except 决策 |
| `Summarizer` 四个方法 | 返回 `None`，内部吞异常 | 调用 `LlmClient.call()`。捕获 `SummarizationEmpty` → 返回 `None`（正常：无摘要生成）；`LLMCallFailed` → 上抛；其余异常 → 上抛 |
| `_background_summarize` | `except Exception: logger.warning` 静默吞 | 捕获 `TransientError` → 日志告警；`FatalError` → 上抛被 `on_task_done` 记录 |
| `forget.py` | `except ValueError, TypeError: continue` 静默跳过 | 损坏条目记录 warning + 跳过；其余异常上抛 |
| `RetrievalPipeline.search()` | embedding 失败透传异常 | **不变**——embedding 调用由 `EmbeddingClient` 经 `EmbeddingModel` 发出，后者已有重试（3次指数退避），失败时异常自然上浮。`RetrievalPipeline` 不吞不包，由调用方 `MemoryBankStore.search()` 统一捕获 |
| `MemoryLifecycle.write()` | 内部吞异常 | 写入失败抛 `FatalError`，由调用方（GraphQL）决定返回错误 |
| `compute_ingestion_forget_ids` | 静默 `return []` | 记录 warning + 返回 `[]`（降级行为） |
| `MemoryLifecycle._background_summarize`（lifecycle.py:204） | `except Exception: logger.warning` | 捕获 `TransientError` → 日志告警；`FatalError` → 上抛被 `on_task_done` 记录 |

### 降级策略

调用链顶层不抛异常，降级为日志 + 安全默认值：

- `MemoryBankStore.search()`：嵌入/检索异常 → 捕获后返回空结果
- `MemoryBankStore.write()`：写入失败 → 抛 `FatalError`（此操作无合理降级）
- 后台任务（`lifecycle.py._background_summarize`）：失败不影响主流程，由 `BackgroundTaskRunner._on_task_done` 记录

---

## 三、配置全量集中

### 从模块常量迁入 `MemoryBankConfig`

所有配置参数统一归入 `MemoryBankConfig`（pydantic-settings，`MEMORYBANK_` 前缀）。

```python
class MemoryBankConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORYBANK_", case_sensitive=False)

    # ── 遗忘 ──
    enable_forgetting: bool = False
    forget_mode: Literal["deterministic", "probabilistic"] = "deterministic"
    soft_forget_threshold: float = 0.15
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0   # ← 从 forget.py 模块常量迁入
    seed: int | None = None

    # ── 检索 ──
    chunk_size: int | None = None
    default_chunk_size: int = 1500
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    # ── LLM ──（新增）
    llm_max_retries: int = 3             # ← llm.py LLM_MAX_RETRIES
    llm_trim_start: int = 1800           # ← llm.py LLM_TRIM_START
    llm_trim_step: int = 200             # ← llm.py LLM_TRIM_STEP
    llm_trim_min: int = 500              # ← llm.py LLM_TRIM_MIN
    llm_anchor_user: str = "Hello! Please help me summarize the content of the conversation."
    llm_anchor_assistant: str = "Sure, I will do my best to assist you."
    llm_temperature: float | None = None # None = 使用 ChatModel 默认
    llm_max_tokens: int | None = None    # None = 使用 ChatModel 默认

    # ── 摘要 ──
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    # ── 嵌入 ──
    embedding_dim: int = 1536
    embedding_batch_size: int = 32       # ← 新增（对齐 VMB）

    # ── 关闭 ──
    shutdown_timeout_seconds: float = 30.0
    reference_date: str | None = None
```

### 受影响的旧常量

| 旧位置 | 常量 | 迁移后 |
|--------|------|--------|
| `llm.py:16` | `LLM_MAX_RETRIES` | `config.llm_max_retries` |
| `llm.py:18-20` | `LLM_TRIM_START/STEP/MIN` | `config.llm_trim_start/step/min` |
| `llm.py:42-43` | `_ANCHOR_USER/ASSISTANT` | `config.llm_anchor_user/assistant` |
| `forget.py:20` | `FORGETTING_TIME_SCALE` | `config.forgetting_time_scale` |

### 用法

```python
# llm.py LlmClient
async def call(self, prompt: str, *, system_prompt: str) -> str:
    """调用 ChatModel.generate()，成功返回非空 str。
    
    Raises:
        LLMCallFailed: API 调用失败（网络/超时/限速/5xx），重试耗尽
        SummarizationEmpty: LLM 返回空内容——非错误，哨兵异常
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": self._config.llm_anchor_user},
        {"role": "assistant", "content": self._config.llm_anchor_assistant},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(self._config.llm_max_retries):
        cut = max(self._config.llm_trim_start - self._config.llm_trim_step * attempt,
                  self._config.llm_trim_min)
        ...
```

### 权衡

- **优**：一处置全局生效；环境变量覆盖所有阈值；新成员无需猜常量位置
- **劣**：`MemoryBankConfig` 字段 ~25，需分块注释维持可读性

---

## 四、索引损坏恢复降级

### 当前问题

加载时任何错误（JSON 解析、类型错、count mismatch）→ 删除全部三文件，重建空索引。后果：向量全丢，嵌入 API 成本不可挽回。

### 新策略：三级降级

| 损坏类型 | 恢复策略 |
|----------|----------|
| `metadata.json` 格式错 | 从 FAISS 索引重建 metadata 骨架（faiss_id+空 text+`corrupted=True`） |
| `extra_metadata.json` 损坏 | 忽略，空 dict 启动（下次摘要自动重建） |
| Count mismatch（ntotal ≠ len(metadata)） | 以 index 为权威：追加缺失骨架 metadata 条目 |
| `index.faiss` 读失败/格式错 | 唯一需删除场景——但先备份 `.bak`，再重建空索引 |

### 实现

```python
@dataclass
class LoadResult:
    ok: bool
    warnings: list[str]
    recovery_actions: list[str]  # 人类可读的恢复描述

class FaissIndex:
    async def load(self) -> LoadResult: ...
```

`LoadResult` 由 `MemoryBankStore.__init__` 消费——若 `warnings` 非空则 `logger.warning`；若 `recovery_actions` 非空则 `logger.info`。

### 降级逻辑要点

1. **metadata 损坏、index 正常**：
   - 遍历 `n = index.ntotal`，生成 items：`{"faiss_id": i, "text": "", "corrupted": True, "memory_strength": 1, "timestamp": ""}`
   - FAISS 内积检索仍可工作（score 有效），但 `text` 为空
   - `corrupted` 字段仅存在于 `FaissIndex._metadata` 内部 dict，不进入 `MemoryEvent` / `SearchResult` Pydantic 模型——由 `MemoryBankStore.search()` 在构建 `SearchResult` 前过滤

2. **count mismatch**：
   - 以 index 为权威（保向量不丢），为缺失 ID 补骨架 entry
   - 多余的 metadata（有 entry 无向量）保留但标记 `orphaned=True`
   - `orphaned` 同 corrupted：仅内部标记，不影响外部 schema

3. **index.faiss 不可读**：
   - `shutil.copy(index_path, index_path.with_suffix(".faiss.bak"))`
   - 删除原文件，重建空索引
   - 保留 `.bak` 供事后排查

### 权衡

- **优**：metadata 损坏不丢向量（嵌入成本最高）；`.bak` 保留原始字节；降级后系统仍服务
- **劣**：reconstruct 条目 text 为空 → 检索结果无文本，需 UI 处理
- **弃案**：始终全删——不可逆；WAL 日志——过重

---

## 五、影响文件总表

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `app/memory/exceptions.py` | **新增** | ~50 行 |
| `app/memory/memory.py` | 改 | +20 行 |
| `app/memory/memory_bank/config.py` | 改 | +15 字段 |
| `app/memory/memory_bank/llm.py` | 改 | 模块常量 → config |
| `app/memory/memory_bank/forget.py` | 改 | 模块常量 → config；异常改造 |
| `app/memory/memory_bank/index.py` | 改 | load() 返回值从 None → LoadResult |
| `app/memory/memory_bank/lifecycle.py` | 改 | 异常抛而非吞 |
| `app/memory/memory_bank/summarizer.py` | 改 | 异常抛而非返回 None |
| `app/memory/memory_bank/store.py` | 改 | 构造时收 user_id，消费 LoadResult |
| `app/memory/memory_bank/retrieval.py` | 不变 | embedding 异常由下层自然上浮，此层不吞不包 |
| `app/memory/memory_bank/index_reader.py` | 不变 | |
| `app/memory/memory_bank/bg_tasks.py` | 不变 | `_on_task_done` 已记录异常，无需改 |
| `app/memory/interfaces.py` | 改 | 追加 `close()` 方法至 Protocol |
| `app/memory/schemas.py` | 不变 | `corrupted`/`orphaned` 仅 metadata 内部字段，不入 Pydantic |
| `app/memory/embedding_client.py` | 不变 | |

## 未解决问题

1. 内存中同时持有多个 store 实例（每用户一个），车载场景 ≤6 用户，每实例开销 ~10MB（FAISS 索引），总量可控。若未来需大量用户，需 LRU 淘汰策略
2. `MemoryStore` Protocol 加 `close()` 方法（无默认实现，协议定义即可）——后续接口统一，避免 `isinstance` 判断。追加至 `interfaces.py`
3. 损坏恢复的 `corrupted=True` 条目在 `MemoryBankStore.search()` 中过滤——`SearchResult` 构建时跳过，不传入 GraphQL resolver。此决策与降级逻辑要点一致（store 层清理，避免污染上层）
