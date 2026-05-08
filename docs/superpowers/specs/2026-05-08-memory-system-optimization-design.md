# 记忆系统优化与 VehicleMemBench 对齐

## 背景

DrivePal 的记忆系统（`app/memory/`）从 VehicleMemBench 的 MemoryBank 实验组移植而来，核心检索/遗忘/摘要算法一致，但在移植过程中引入了若干正确性 bug 和冗余代码。本次优化目标：修复全部 bug、精简冗余、对齐 VehicleMemBench 的算法行为。

**优先级**：正确性 > 功能完善 > 代码简洁。不保证接口兼容。

## 修改清单

### 1. 负分惩罚逻辑修正

**文件**：`app/memory/memory_bank/retrieval.py` → `_apply_speaker_filter()`

**问题**：当前 `r["score"] = score * 0.75` 统一乘 0.75。对负分，绝对值缩小 → 排名提升，与惩罚意图相反。

**修正**：正分 ×0.75（降低排名），负分 ×1.25（加重惩罚）。

```python
score = r.get("score", 0.0)
r["score"] = score * 0.75 if score >= 0 else score * 1.25
```

**来源**：VehicleMemBench `memorybank.py` line 1678。

### 2. First name 匹配

**文件**：`app/memory/memory_bank/retrieval.py` → `_apply_speaker_filter()`

**问题**：说话人过滤仅匹配全名（如 "Gary Smith"），query 中 "Gary" 无法命中。

**修正**：拆分 first name，全名和 first name 同时匹配。

```python
speakers_in_query: set[str] = set()
for r in results:
    for spk in r.get("speakers") or []:
        spk_lower = spk.lower()
        first = spk.split(" ", 1)[0].lower() if " " in spk else spk_lower
        if _word_in_text(spk_lower, ql) or _word_in_text(first, ql):
            speakers_in_query.add(spk_lower)
```

**来源**：VehicleMemBench `memorybank.py` line 1660-1663。

### 3. EmbeddingClient 精简

**文件**：`app/memory/embedding_client.py`

**问题**：
- `encode_batch()` 逐条调用 `encode()`，未利用 `EmbeddingModel.batch_encode()` 的 OpenAI 批量 API。
- 自带重试逻辑（5 次 + 指数退避 + jitter），与 `EmbeddingModel` 内置重试（3 次）冗余。

**修正**：改造为薄代理，只添加维度一致性检测：

```python
class EmbeddingClient:
    """EmbeddingModel 薄代理，添加维度一致性检测。"""

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        self._model = embedding_model

    async def encode(self, text: str) -> list[float]:
        return await self._model.encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results = await self._model.batch_encode(texts)
        dims = {len(v) for v in results}
        if len(dims) > 1:
            raise RuntimeError(
                f"Embedding dimension mismatch: {dims}. "
                f"All vectors must have the same dimension."
            )
        return results
```

**移除**：`MAX_RETRIES`、`BACKOFF_BASE`、`BATCH_SIZE`、`_TRANSIENT_PATTERNS`、`_SLEEP`、`_rng` 参数、所有重试逻辑。

**来源**：维度检测移植自 VehicleMemBench `memorybank.py` line 639-643。

### 4. LLM 4 消息序列

**4.1 ChatModel 扩展**

**文件**：`app/models/chat.py` → `ChatModel.generate()`

**修改**：增加可选 `messages` 参数：

```python
async def generate(
    self,
    prompt: str,
    system_prompt: str | None = None,
    messages: list[dict] | None = None,
) -> str:
```

- `messages` 非空时直接用作 API 的 messages 列表，忽略 `prompt`/`system_prompt`。
- `messages` 为空时走现有路径（向后兼容）。

**4.2 LlmClient 改造**

**文件**：`app/memory/memory_bank/llm.py`

**修改**：`call()` 方法构建 4 消息序列（system → user → assistant → user），对齐 VehicleMemBench 的角色锚定：

```python
messages = [
    {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
    {"role": "user", "content": "Hello! Please help me summarize the content of the conversation."},
    {"role": "assistant", "content": "Sure, I will do my best to assist you."},
    {"role": "user", "content": prompt},
]
```

重试逻辑中上下文超长截断改为截断 `messages[-1]["content"]`：

```python
# 上下文超长时，截断 messages 中最后一条 user 消息
cut = max(LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN)
messages[-1]["content"] = messages[-1]["content"][-cut:]
```

`ChatModel.generate(messages=messages)` 传入完整消息序列。

**来源**：VehicleMemBench `memorybank.py` line 1086-1117。

### 5. 死代码移除

**5.1 FeedbackManager**

- 删除 `app/memory/components.py` 中的 `FeedbackManager`、`ActionRequiredError`、`_strategy_locks`、`_strategy_locks_lock`、`SUMMARY_WEIGHT`。
- `app/memory/memory_bank/store.py`：移除 `from app.memory.components import FeedbackManager` 导入，移除 `self._feedback` 初始化，`update_feedback()` 方法体改为 `raise NotImplementedError("Feedback not supported")`。
- `app/memory/schemas.py`：`FeedbackData` 保留（GraphQL schema 可能引用）。
- `app/memory/__init__.py`：从 `__all__` 移除 `FeedbackData`。

**5.2 KeywordSearch**

- 删除 `app/memory/components.py` 中的 `KeywordSearch` 类。无调用方。

**5.3 components.py 文件清理**

移除后若 `components.py` 为空，删除整个文件并移除所有 import。

### 6. 常量对齐

**文件**：`app/memory/memory_bank/store.py` → `search()` 方法

**修改**：`top_k` 参数默认值从 10 改为 5，与 VehicleMemBench `DEFAULT_TOP_K = 5` 一致。

同步修改 `MemoryModule.search()` 和 `MemoryStore.search()` Protocol 中的 `top_k` 默认值。

## 不在本次范围

- 多用户支持（VehicleMemBench 有 per-user 索引，DrivePal 为单用户设计）
- 批量摄入接口（`run_add` 评测专用）
- `format_search_results()` 评测格式化
- LLM temperature/top_p/frequency_penalty/presence_penalty 参数暴露（由 ChatModel 内部管理）
- `DEFAULT_TIME_SUFFIX` 等评测专用常量

## 影响的文件

### 源码

| 文件 | 改动类型 |
|------|----------|
| `app/memory/memory_bank/retrieval.py` | bug 修复（负分 + first name） |
| `app/memory/embedding_client.py` | 重写（精简为薄代理） |
| `app/memory/memory_bank/llm.py` | 改造（4 消息序列 + 截断目标变更） |
| `app/models/chat.py` | 扩展（`messages` 参数） |
| `app/memory/memory_bank/store.py` | 移除 `self._feedback` 初始化 + `update_feedback()` 改为 `raise NotImplementedError` + top_k 默认值 |
| `app/memory/components.py` | 删除整个文件（FeedbackManager + KeywordSearch 移除后为空） |
| `app/memory/__init__.py` | 移除 `FeedbackData` 导出 |
| `app/memory/interfaces.py` | `top_k` 默认值 10 → 5 |
| `app/memory/memory.py` | `top_k` 默认值 10 → 5 |

### 测试

| 文件 | 改动 |
|------|------|
| `tests/test_embedding.py` | 更新：`EmbeddingClient` 构造签名变更（去掉 rng 参数），验证 `encode_batch` 使用 `batch_encode` |
| `tests/stores/test_memory_bank_store.py` | 更新：`update_feedback` 测试改为断言 `NotImplementedError` |
| `tests/stores/test_retrieval.py` | 新增：负分惩罚测试、first name 匹配测试 |
| `tests/test_memory_store_contract.py` | 更新：`top_k` 默认值变更，`update_feedback` 契约 |
| `tests/test_memory_module_facade.py` | 更新：`top_k` 默认值变更 |
| 含 FeedbackManager 的测试文件 | 删除或移除相关测试用例 |
