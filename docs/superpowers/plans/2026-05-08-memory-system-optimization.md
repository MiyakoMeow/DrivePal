# 记忆系统优化与 VehicleMemBench 对齐 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复记忆系统 5 类正确性 bug、精简 EmbeddingClient 冗余重试、对齐 VehicleMemBench 的 LLM 角色锚定、移除死代码。

**架构：** 保持现有 Facade + Protocol 模式。改动集中在检索管道 bug 修复、EmbeddingClient 精简为薄代理、LlmClient 改为 4 消息序列、ChatModel 扩展 messages 参数、移除 FeedbackManager/KeywordSearch。

**技术栈：** Python 3.14, FAISS, openai SDK, pytest

---

## 文件结构

### 源码

| 文件 | 职责 |
|------|------|
| `app/memory/memory_bank/retrieval.py` | 检索管道：负分惩罚修正 + first name 匹配 |
| `app/memory/embedding_client.py` | 精简为 EmbeddingModel 薄代理 + 维度检测 |
| `app/memory/memory_bank/llm.py` | 4 消息序列 + messages 截断 |
| `app/models/chat.py` | `generate()` 扩展 `messages` 参数 |
| `app/memory/memory_bank/store.py` | 移除 FeedbackManager 引用 + top_k=5 |
| `app/memory/components.py` | 整个文件删除 |
| `app/memory/__init__.py` | 移除 FeedbackData 导出 |
| `app/memory/interfaces.py` | top_k 默认值 10→5 |
| `app/memory/memory.py` | top_k 默认值 10→5 |

### 测试

| 文件 | 改动 |
|------|------|
| `tests/stores/test_retrieval.py` | 新增负分惩罚 + first name 匹配测试 |
| `tests/stores/test_llm.py` | 更新 mock 模型支持 messages 参数 |
| `tests/test_embedding.py` | EmbeddingClient 构造签名变更 |
| `tests/test_components.py` | 整个文件删除 |
| `tests/stores/test_memory_bank_store.py` | 新增 update_feedback NotImplementedError 测试 |
| `tests/test_memory_store_contract.py` | top_k 默认值变更 |
| `tests/test_memory_module_facade.py` | top_k 默认值变更 |

---

### 任务 1：负分惩罚逻辑修正

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py:440`
- 测试：`tests/stores/test_retrieval.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/stores/test_retrieval.py` 末尾追加：

```python
def test_speaker_filter_negative_score_penalty():
    """负分时惩罚应加重（绝对值增大），非缩小。"""
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    results = [
        {
            "speakers": ["Alice"],
            "score": 0.9,
            "text": "relevant",
        },
        {
            "speakers": ["Bob"],
            "score": -0.5,
            "text": "irrelevant",
        },
    ]
    filtered = pipe._apply_speaker_filter(results, "Alice")
    # 正分 ×0.75：0.9 → 0.675
    assert filtered[0]["score"] == 0.9  # Alice 相关，不降权
    # 负分 ×1.25：-0.5 → -0.625（更负 = 排名更低）
    assert filtered[1]["score"] == -0.625
```

- [ ] **步骤 2：运行测试验证失败**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py::test_speaker_filter_negative_score_penalty -v`
预期：FAIL，`assert filtered[1]["score"] == -0.625`（实际为 -0.375，因为 -0.5 * 0.75 = -0.375）

- [ ] **步骤 3：修复负分惩罚逻辑**

在 `app/memory/memory_bank/retrieval.py` 的 `_apply_speaker_filter()` 方法中，将：

```python
r["score"] = r.get("score", 0.0) * 0.75
```

替换为：

```python
score = r.get("score", 0.0)
r["score"] = score * 0.75 if score >= 0 else score * 1.25
```

- [ ] **步骤 4：运行测试验证通过**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py::test_speaker_filter_negative_score_penalty -v`
预期：PASS

- [ ] **步骤 5：运行全量 retrieval 测试**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py -v`
预期：全部 PASS

- [ ] **步骤 6：Commit**

```bash
git add app/memory/memory_bank/retrieval.py tests/stores/test_retrieval.py
git commit -m "fix: negative score penalty in speaker filter"
```

---

### 任务 2：First name 匹配

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py:427-441`
- 测试：`tests/stores/test_retrieval.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/stores/test_retrieval.py` 末尾追加：

```python
def test_speaker_filter_first_name_matching():
    """query 中 first name 应匹配全名说话人。"""
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    results = [
        {
            "speakers": ["Gary Smith"],
            "score": 0.9,
            "text": "Gary's preference",
        },
        {
            "speakers": ["Patricia Johnson"],
            "score": 0.8,
            "text": "Patricia's preference",
        },
    ]
    filtered = pipe._apply_speaker_filter(results, "Gary seat preference")
    # Gary Smith 匹配（first name "Gary" 命中 query），不降权
    gary = next(r for r in filtered if "Gary" in r.get("speakers", []))
    assert gary["score"] == 0.9
    # Patricia 不匹配，降权
    patricia = next(r for r in filtered if "Patricia" in r.get("speakers", []))
    assert patricia["score"] == 0.6  # 0.8 * 0.75
```

- [ ] **步骤 2：运行测试验证失败**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py::test_speaker_filter_first_name_matching -v`
预期：FAIL，Gary Smith 未被识别为 query 中的说话人（全名 "Gary Smith" 不在 query "Gary seat preference" 中）

- [ ] **步骤 3：实现 first name 匹配**

在 `app/memory/memory_bank/retrieval.py` 的 `_apply_speaker_filter()` 方法中，将：

```python
ql = query.lower()
speakers_in_query = {
    s.lower()
    for r in results
    for s in (r.get("speakers") or [])
    if _word_in_text(s.lower(), ql)
}
```

替换为：

```python
ql = query.lower()
speakers_in_query: set[str] = set()
for r in results:
    for spk in r.get("speakers") or []:
        spk_lower = spk.lower()
        first = spk.split(" ", 1)[0].lower() if " " in spk else spk_lower
        if _word_in_text(spk_lower, ql) or _word_in_text(first, ql):
            speakers_in_query.add(spk_lower)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py::test_speaker_filter_first_name_matching -v`
预期：PASS

- [ ] **步骤 5：运行全量 retrieval 测试**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py -v`
预期：全部 PASS

- [ ] **步骤 6：Commit**

```bash
git add app/memory/memory_bank/retrieval.py tests/stores/test_retrieval.py
git commit -m "fix: speaker filter first name matching"
```

---

### 任务 3：EmbeddingClient 精简为薄代理

**文件：**
- 重写：`app/memory/embedding_client.py`
- 测试：`tests/stores/test_retrieval.py`（构造签名变更）、`tests/test_embedding.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/stores/test_retrieval.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_embedding_client_uses_batch_encode():
    """EmbeddingClient.encode_batch 应调用 EmbeddingModel.batch_encode。"""
    from unittest.mock import AsyncMock

    model = AsyncMock(spec=["encode", "batch_encode"])
    model.batch_encode.return_value = [[0.1] * 1536, [0.2] * 1536]
    client = EmbeddingClient(model)
    results = await client.encode_batch(["text1", "text2"])
    assert len(results) == 2
    model.batch_encode.assert_awaited_once_with(["text1", "text2"])


@pytest.mark.asyncio
async def test_embedding_client_dimension_mismatch_raises():
    """维度不一致时应抛出 RuntimeError。"""
    from unittest.mock import AsyncMock

    model = AsyncMock(spec=["encode", "batch_encode"])
    model.batch_encode.return_value = [[0.1] * 1536, [0.2] * 768]
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        await client.encode_batch(["text1", "text2"])
```

- [ ] **步骤 2：运行测试验证失败**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py::test_embedding_client_uses_batch_encode tests/stores/test_retrieval.py::test_embedding_client_dimension_mismatch_raises -v`
预期：FAIL（EmbeddingClient 当前构造签名需要 rng 参数可选，encode_batch 不调用 batch_encode）

- [ ] **步骤 3：重写 EmbeddingClient**

将 `app/memory/embedding_client.py` 全部内容替换为：

```python
"""EmbeddingModel 薄代理，添加维度一致性检测。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingClient:
    """EmbeddingModel 的薄代理，添加维度一致性检测。

    重试逻辑由 EmbeddingModel 内部处理（3 次指数退避），
    此处不再冗余重试。
    """

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        """初始化 EmbeddingClient。

        Args:
            embedding_model: 嵌入模型实例。

        """
        self._model = embedding_model

    async def encode(self, text: str) -> list[float]:
        """编码单条文本。"""
        return await self._model.encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码，使用 EmbeddingModel.batch_encode 并检测维度一致性。"""
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

- [ ] **步骤 4：更新受影响的构造调用**

`app/memory/memory_bank/store.py` 中 `EmbeddingClient` 的构造可能传入 `rng` 参数。检查并移除 `rng` 相关参数：

当前代码（约 line 86-88）：
```python
self._embedding_client = embedding_client or (
    EmbeddingClient(embedding_model) if embedding_model else None
)
```

无需改动（当前构造已无 rng）。

- [ ] **步骤 5：运行测试验证通过**

运行：`nix develop --command uv run pytest tests/stores/test_retrieval.py -v`
预期：全部 PASS（包括新增的两个测试）

- [ ] **步骤 6：运行 lint 检查**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format`
修复任何 lint 问题。

- [ ] **步骤 7：运行全量记忆系统测试**

运行：`nix develop --command uv run pytest tests/stores/ tests/test_embedding.py -v`
预期：全部 PASS

- [ ] **步骤 8：Commit**

```bash
git add app/memory/embedding_client.py tests/stores/test_retrieval.py
git commit -m "refactor: simplify EmbeddingClient to thin proxy with dim check"
```

---

### 任务 4：ChatModel 扩展 messages 参数

**文件：**
- 修改：`app/models/chat.py:124-146`

- [ ] **步骤 1：扩展 ChatModel.generate()**

在 `app/models/chat.py` 的 `ChatModel.generate()` 方法中：

将签名从：
```python
async def generate(
    self,
    prompt: str,
    system_prompt: str | None = None,
    **_kwargs: object,
) -> str:
```

改为：
```python
async def generate(
    self,
    prompt: str = "",
    system_prompt: str | None = None,
    messages: list[ChatCompletionMessageParam] | None = None,
    **_kwargs: object,
) -> str:
```

将方法体中 `messages = self._build_messages(prompt, system_prompt)` 行改为：

```python
if messages is None:
    messages = self._build_messages(prompt, system_prompt)
```

同步修改 `generate_stream()` 方法，添加相同的 `messages` 参数和分支逻辑。

- [ ] **步骤 2：运行现有 ChatModel 测试确认无回归**

运行：`nix develop --command uv run pytest tests/ -k "chat" -v`
预期：全部 PASS（向后兼容，messages=None 走原路径）

- [ ] **步骤 3：运行 lint 检查**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format`

- [ ] **步骤 4：Commit**

```bash
git add app/models/chat.py
git commit -m "feat: extend ChatModel.generate() with messages parameter"
```

---

### 任务 5：LlmClient 4 消息序列

**文件：**
- 重写：`app/memory/memory_bank/llm.py`
- 测试：`tests/stores/test_llm.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/stores/test_llm.py` 末尾追加：

```python
class _MessagesRecorder:
    """记录 generate() 收到的 messages 参数。"""

    def __init__(self, response: str = "test response"):
        self.response = response
        self.last_messages = None
        self.call_count = 0

    async def generate(self, *, prompt=None, system_prompt=None, messages=None, **_kwargs):
        self.call_count += 1
        self.last_messages = messages
        if messages is not None:
            return self.response
        return self.response


@pytest.mark.asyncio
async def test_llm_sends_four_message_sequence():
    """LlmClient.call() 应构建 4 消息序列（system→user→assistant→user）。"""
    recorder = _MessagesRecorder()
    client = LlmClient(recorder)
    await client.call("summarize this", system_prompt="You are a helper")
    assert recorder.last_messages is not None
    assert len(recorder.last_messages) == 4
    assert recorder.last_messages[0] == {"role": "system", "content": "You are a helper"}
    assert recorder.last_messages[1]["role"] == "user"
    assert recorder.last_messages[2]["role"] == "assistant"
    assert recorder.last_messages[3]["role"] == "user"
    assert recorder.last_messages[3]["content"] == "summarize this"


@pytest.mark.asyncio
async def test_llm_context_trim_shortens_last_message():
    """上下文超长时应截断 messages[-1]["content"]。"""
    recorder = _MessagesRecorder()
    # 首次调用触发上下文超长，二次成功
    call_count = 0

    async def _generate(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AllProviderFailedError("maximum context length exceeded")
        return "trimmed response"

    recorder.generate = _generate
    client = LlmClient(recorder)
    long_prompt = "X" * 2000
    result = await client.call(long_prompt)
    assert result == "trimmed response"
    assert call_count == 2
```

- [ ] **步骤 2：运行测试验证失败**

运行：`nix develop --command uv run pytest tests/stores/test_llm.py::test_llm_sends_four_message_sequence -v`
预期：FAIL（当前 LlmClient 不构建 4 消息序列）

- [ ] **步骤 3：改造 LlmClient.call()**

将 `app/memory/memory_bank/llm.py` 全部内容替换为：

```python
"""ChatModel 薄封装：4 消息序列 + 重试时自动截断 prompt 上下文。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models.chat import AllProviderFailedError

if TYPE_CHECKING:
    import random

logger = logging.getLogger(__name__)

LLM_MAX_RETRIES = 3
LLM_NONTRANSIENT_MAX_RETRIES = 1
LLM_TRIM_START = 1800
LLM_TRIM_STEP = 200
LLM_TRIM_MIN = 500

_sleep = asyncio.sleep

_TRANSIENT_PATTERNS = (
    "connection",
    "timeout",
    "rate limit",
    "eof",
    "reset",
    "service unavailable",
    "bad gateway",
    "internal server error",
)
_CONTEXT_EXCEEDED_PATTERNS = (
    "maximum context",
    "context length",
    "too long",
    "reduce the length",
    "input length",
)

_ANCHOR_USER = "Hello! Please help me summarize the content of the conversation."
_ANCHOR_ASSISTANT = "Sure, I will do my best to assist you."
_DEFAULT_SYSTEM = (
    "You are an in-car AI assistant with expertise in remembering "
    "vehicle preferences, driving habits, and in-car conversation context."
)


class LlmClient:
    """ChatModel 的薄封装，4 消息序列 + 上下文截断重试。"""

    def __init__(self, chat_model: object, *, rng: random.Random | None = None) -> None:
        """初始化 LlmClient。

        Args:
            chat_model: 聊天模型实例（须有 generate 方法）。
            rng: 可选 RNG 实例（用于重试退避 jitter）。

        """
        self._chat_model = chat_model
        self._rng = rng

    async def call(
        self, prompt: str, *, system_prompt: str | None = None
    ) -> str | None:
        """调用 ChatModel.generate()，使用 4 消息序列。

        消息序列：system → user（锚定）→ assistant（应承）→ user（实际 prompt）。
        重试时截断 messages[-1]["content"]。
        """
        messages = [
            {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
            {"role": "user", "content": _ANCHOR_USER},
            {"role": "assistant", "content": _ANCHOR_ASSISTANT},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(LLM_MAX_RETRIES):
            try:
                resp = await self._chat_model.generate(messages=messages)
                return resp.strip() if resp else ""
            except AllProviderFailedError as exc:
                err = str(exc).lower()
                # 上下文超长 → 截断最后一条 user 消息
                if (
                    any(p in err for p in _CONTEXT_EXCEEDED_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    cut = max(
                        LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN
                    )
                    messages[-1]["content"] = messages[-1]["content"][-cut:]
                    continue
                # 瞬态错误 → 指数退避
                if (
                    any(p in err for p in _TRANSIENT_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    delay = min(2**attempt, 10)
                    if self._rng is not None:
                        delay += self._rng.random() * 0.5
                    await _sleep(delay)
                    continue
                # 非瞬态错误：快速失败
                if attempt < LLM_NONTRANSIENT_MAX_RETRIES:
                    continue
                logger.warning(
                    "LlmClient retries exhausted after %d attempts: %s",
                    attempt + 1,
                    exc,
                )
                return None
        return None
```

- [ ] **步骤 4：更新现有测试的 mock 模型**

`tests/stores/test_llm.py` 中的 `_ConstErrorModel`、`_AlternatingModel`、`_ContextTrimModel` 的 `generate()` 方法使用 `**_kwargs` 签名，已兼容 `messages=` 参数。无需改动。

但 `_ContextTrimModel` 需要验证 `messages` 参数被正确传入。检查现有测试是否仍然通过。

- [ ] **步骤 5：运行全量 LlmClient 测试**

运行：`nix develop --command uv run pytest tests/stores/test_llm.py -v`
预期：全部 PASS（新增 2 个测试 + 现有 4 个测试）

- [ ] **步骤 6：运行 lint 检查**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format`

- [ ] **步骤 7：Commit**

```bash
git add app/memory/memory_bank/llm.py tests/stores/test_llm.py
git commit -m "feat: LlmClient 4-message sequence for role anchoring"
```

---

### 任务 6：移除死代码（FeedbackManager + KeywordSearch）

**文件：**
- 删除：`app/memory/components.py`
- 删除：`tests/test_components.py`
- 修改：`app/memory/memory_bank/store.py`
- 修改：`app/memory/__init__.py`

- [ ] **步骤 1：移除 store.py 中 FeedbackManager 引用**

在 `app/memory/memory_bank/store.py` 中：

a) 删除导入行：
```python
from app.memory.components import FeedbackManager
```

b) 删除 `__init__` 中的初始化：
```python
self._feedback = FeedbackManager(data_dir)
```

c) 将 `update_feedback()` 方法体从：
```python
await self._feedback.update_feedback(event_id, feedback)
```
改为：
```python
raise NotImplementedError("Feedback not supported")
```

- [ ] **步骤 2：更新 __init__.py**

在 `app/memory/__init__.py` 中：
- 从导入列表移除 `FeedbackData`
- 从 `__all__` 移除 `"FeedbackData"`

- [ ] **步骤 3：删除 components.py**

删除 `app/memory/components.py`。

- [ ] **步骤 4：删除测试文件**

删除 `tests/test_components.py`。

- [ ] **步骤 5：验证无残留引用**

运行：`rg -l "components" app/ tests/ --type py`
预期：无匹配（所有 components 引用已清除）

- [ ] **步骤 6：运行全量测试**

运行：`nix develop --command uv run pytest tests/ -v --ignore=tests/test_components.py`
预期：全部 PASS

- [ ] **步骤 7：运行 lint + type check**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format && nix develop --command uv run ty check`

- [ ] **步骤 8：Commit**

```bash
git add -A
git commit -m "refactor: remove FeedbackManager, KeywordSearch, and components.py"
```

---

### 任务 7：常量对齐 top_k=5

**文件：**
- 修改：`app/memory/memory_bank/store.py`
- 修改：`app/memory/interfaces.py`
- 修改：`app/memory/memory.py`

- [ ] **步骤 1：修改 store.py**

在 `app/memory/memory_bank/store.py` 的 `search()` 方法中，将 `top_k: int = 10` 改为 `top_k: int = 5`。

- [ ] **步骤 2：修改 interfaces.py**

在 `app/memory/interfaces.py` 的 `MemoryStore.search()` Protocol 中，将 `top_k: int = 10` 改为 `top_k: int = 5`。

- [ ] **步骤 3：修改 memory.py**

在 `app/memory/memory.py` 的 `MemoryModule.search()` 方法中，将 `top_k: int = 10` 改为 `top_k: int = 5`。

- [ ] **步骤 4：运行相关测试**

运行：`nix develop --command uv run pytest tests/test_memory_store_contract.py tests/test_memory_module_facade.py tests/stores/test_memory_bank_store.py -v`
预期：全部 PASS

- [ ] **步骤 5：运行 lint**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format`

- [ ] **步骤 6：Commit**

```bash
git add app/memory/memory_bank/store.py app/memory/interfaces.py app/memory/memory.py
git commit -m "refactor: align DEFAULT_TOP_K to 5 (VehicleMemBench parity)"
```

---

### 任务 8：最终验证

- [ ] **步骤 1：运行全量测试**

运行：`nix develop --command uv run pytest -v`
预期：全部 PASS

- [ ] **步骤 2：运行 lint + type check**

运行：`nix develop --command uv run ruff check --fix && nix develop --command uv run ruff format && nix develop --command uv run ty check`
预期：无错误

- [ ] **步骤 3：验证无禁用标记**

运行：`rg "# noqa|# type:" app/ --type py`
预期：无匹配（项目禁止内联抑制）
