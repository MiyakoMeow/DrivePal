# 第二批：P2 架构加固 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 5 项架构加固：LLM 输出结构验证、AgentState TypedDict、\_ensure\_loaded 优化、合并丢弃追踪、平铺迁移简化。

**架构：** 任务 2.1 与 2.2 同改 `workflow.py` 需顺序执行。其余独立。

**技术栈：** Python 3.14, Pydantic, TypedDict, asyncio

**设计规格：** `docs/superpowers/specs/2026-05-12-refactoring-plan.md` 第 2 节

---

### 任务 2.1：LLM JSON 输出结构化验证

**文件：**
- 修改：`app/agents/workflow.py` — 加输出模型；`_call_llm_json` 后加校验
- 测试：`tests/test_llm_json_validation.py`（新建）

**说明：**
`LLMJsonResponse` 目前 `extra="allow"`，任何 JSON 都通过。改为三阶段各建 Pydantic 模型，校验失败走兜底。

**模型定义（放 `workflow.py` 或新建 `app/agents/output_models.py`）：**
- `ContextOutput(BaseModel)`: model_config = ConfigDict(extra="forbid"); scenario: str = ""; driver_state: dict = {}; spatial: dict = {}; traffic: dict = {}; current_datetime: str = ""; related_events: list = []; conversation_history: list | None = None
- `TaskOutput(BaseModel)`: type: str = "general"; confidence: float = 0.0; description: str = ""; entities: list = []
- `StrategyOutput(BaseModel)`: should_remind: bool = True; timing: str = "now"; target_time: str = ""; delay_seconds: int = 300; reminder_content: str | dict = ""; type: str = "general"; reason: str = ""; allowed_channels: list = []; action: str = ""; postpone: bool = False
- `LLMJsonResponse` 改 `extra="forbid"`

**各节点改动：**
- `_context_node`: `ContextOutput.model_validate(parsed)` 校验，失败则 `logger.warning` + 仍用 parsed（兜底）
- `_task_node`: 同理
- `_strategy_node`: 同理

- [ ] **步骤 1：编写测试**

```python
"""LLM JSON 输出结构化验证测试。"""
import json
import pytest
from pydantic import ValidationError

from app.agents.workflow import (
    ContextOutput, TaskOutput, StrategyOutput, LLMJsonResponse,
)


class TestContextOutput:
    def test_valid_minimal(self):
        """最少字段通过验证。"""
        data = {"scenario": "highway", "driver_state": {}, "spatial": {},
                "traffic": {}, "current_datetime": "2026-01-01"}
        ctx = ContextOutput.model_validate(data)
        assert ctx.scenario == "highway"

    def test_extra_fields_rejected(self):
        """extra 字段触发验证错误。"""
        data = {"scenario": "parked", "driver_state": {}, "spatial": {},
                "traffic": {}, "current_datetime": "2026-01-01",
                "unexpected": "should_fail"}
        with pytest.raises(ValidationError):
            ContextOutput.model_validate(data)

    def test_all_fields_default(self):
        """空 dict 使用默认值。"""
        ctx = ContextOutput.model_validate({})
        assert ctx.scenario == ""
        assert ctx.related_events == []


class TestTaskOutput:
    def test_valid_full(self):
        data = {"type": "meeting", "confidence": 0.8, "description": "开会"}
        task = TaskOutput.model_validate(data)
        assert task.type == "meeting"

    def test_extra_rejected(self):
        data = {"type": "travel", "extra": "bad"}
        with pytest.raises(ValidationError):
            TaskOutput.model_validate(data)


class TestStrategyOutput:
    def test_valid_minimal(self):
        data = {"should_remind": True, "timing": "now", "reason": "test"}
        s = StrategyOutput.model_validate(data)
        assert s.should_remind

    def test_extra_rejected(self):
        data = {"should_remind": False, "extra": "bad"}
        with pytest.raises(ValidationError):
            StrategyOutput.model_validate(data)


class TestLLMJsonResponse:
    def test_extra_rejected(self):
        """LLMJsonResponse 改 strict 后，extra 字段应触发验证错误。"""
        text = '{"extra_field": 1, "raw": "x"}'
        with pytest.raises(ValidationError):
            LLMJsonResponse.model_validate({"extra_field": 1, "raw": text})

    def test_from_llm_parses_valid(self):
        resp = LLMJsonResponse.from_llm('{"key": "val"}')
        assert resp.raw == '{"key": "val"}'
        # 仅 raw 字段保留，其余被 forbid 拒绝——from_llm 内部 catch 异常后只返回 raw
        # 这表示 from_llm 需要处理 ValidationError 兜底
        assert resp.raw is not None

    def test_from_llm_invalid_json(self):
        resp = LLMJsonResponse.from_llm("not json")
        assert resp.raw == "not json"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_llm_json_validation.py -v`
预期：模块导入错误

- [ ] **步骤 3：实现输出模型 + 修改 `_call_llm_json`**

在 `workflow.py` 中新增：

```python
from pydantic import BaseModel, ConfigDict

class ContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = ""
    driver_state: dict = {}
    spatial: dict = {}
    traffic: dict = {}
    current_datetime: str = ""
    related_events: list = []
    conversation_history: list | None = None

class TaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = "general"
    confidence: float = 0.0
    description: str = ""
    entities: list = []

class StrategyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    should_remind: bool = True
    timing: str = "now"
    target_time: str = ""
    delay_seconds: int = 300
    reminder_content: str | dict = ""
    type: str = "general"
    reason: str = ""
    allowed_channels: list = []
    action: str = ""
    postpone: bool = False
```

修改 `LLMJsonResponse`：

```python
class LLMJsonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: str

    @classmethod
    def from_llm(cls, text: str) -> "LLMJsonResponse":
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return cls(raw=text, **data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("LLM JSON parse/validate failed: %s", e)
        return cls(raw=text)
```

在各阶段节点中加校验（以 `_context_node` 为例）：

```python
parsed = await self._call_llm_json(prompt)
try:
    validated = ContextOutput.model_validate(parsed.model_dump())
    context = validated.model_dump()
except ValidationError as e:
    logger.warning("ContextOutput validation failed: %s", e)
    # fallback: 从 raw 重新解析（LLMJsonResponse 可能只有 raw 字段）
    try:
        raw_data = json.loads(parsed.raw)
        context = raw_data if isinstance(raw_data, dict) else {}
    except json.JSONDecodeError:
        context = {}
```

同样在 `_task_node` 和 `_strategy_node` 中处理。

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_llm_json_validation.py -v`
预期：全部通过

- [ ] **步骤 5：lint / type check / commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check .
uv run pytest tests/ -v
git add app/agents/workflow.py tests/test_llm_json_validation.py
git commit -m "feat: add Pydantic output validation for LLM JSON responses"
```

---

### 任务 2.2：AgentState 类型标注补全

**文件：**
- 修改：`app/agents/workflow.py` — 所有 `state` 变量加 `: AgentState` 类型标注

**说明：**
`AgentState` 已在 `state.py` 定义为 TypedDict。`workflow.py` 中多处 `state` 变量无显式类型标注或标注为 `dict`。补全 `: AgentState` 让 ty 能检查字段访问正确性。

无功能改动，纯类型标注。

- [ ] **步骤 1：扫描 workflow.py 中所有 state 变量定义，补 `: AgentState`**

```python
# 示例：run_with_stages 中
state: AgentState = {
    "original_query": user_input,
    ...
}

# run_stream 中同理
```

注意 `context_node` 等方法的签名参数 `state` — 已标注 `AgentState` 则可跳过；若标注为 `dict` 则改为 `AgentState`。

- [ ] **步骤 2：运行 type check**

运行：`uv run ty check .`
预期：无 AgentState 相关错误

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/ -v`
预期：376 passed, 22 skipped

- [ ] **步骤 4：commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: add AgentState type annotations to workflow methods"
```

---

### 任务 2.3：`_ensure_loaded` 懒加载优化

**文件：**
- 修改：`app/memory/memory_bank/store.py`

**说明：**
每次操作调 `_ensure_loaded()`，首次后 `_index.load()` 因 `_index is not None` 立即返回，但多一次 async 调用。加 `_loaded: bool` 跳过。

- [ ] **步骤 1：编写测试**

```python
# 追加到 tests/stores/test_memory_store.py

@pytest.mark.asyncio
async def test_ensure_loaded_skips_after_first(tmp_path):
    """_ensure_loaded 首次后应跳过 load 调用。"""
    from app.memory.memory_bank.store import MemoryBankStore
    store = MemoryBankStore(tmp_path, embedding_model=AsyncMock())
    store._index.load = AsyncMock(wraps=store._index.load)
    await store._ensure_loaded()
    call_count_1 = store._index.load.call_count
    await store._ensure_loaded()
    assert store._index.load.call_count == call_count_1  # 未额外调用
```

- [ ] **步骤 2：修改 `store.py`**

```python
# 在 __init__ 中：
self._loaded: bool = False

# _ensure_loaded 方法：
async def _ensure_loaded(self) -> None:
    if self._loaded:
        return
    result = await self._index.load()
    if result.ok:
        self._loaded = True
    # ... 后续 warning/recovery 同现在 ...
```

注意：`_ensure_loaded` 在 `close()` 和 `finalize_ingestion()` 中也会调用，确保加载状态保持一致。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/stores/ -v`
预期：全部通过

- [ ] **步骤 4：commit**

```bash
git add app/memory/memory_bank/store.py
git commit -m "perf: skip _ensure_loaded after first successful load"
```

---

### 任务 2.4：合并结果静默丢弃追踪

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`
- 修改：`app/memory/memory_bank/observability.py`

**说明：**
`_merge_result_group()` 返回 None 时（空文本后），当前静默丢弃。改为 log warning + metrics 增量。

- [ ] **步骤 1：编写测试**

```python
# 追加到 tests/test_retrieval_pipeline.py

@pytest.mark.asyncio
async def test_merge_empty_result_logs_warning(caplog):
    """合并后空文本应产生 warning 日志。"""
    from app.memory.memory_bank.retrieval import _merge_result_group
    merging = [
        {"_merged_indices": [0, 1], "text": "", "score": 0.5, "memory_strength": 1},
        {"_merged_indices": [1, 2], "text": "", "score": 0.4, "memory_strength": 1},
    ]
    # _build_overlap_groups 和 _merge_result_group 的正常调用路径
    # 此测试验证 _merge_result_group 中空文本分支
    members = [0, 1]
    import logging
    with caplog.at_level(logging.WARNING):
        result = _merge_result_group(merging, members)
    assert result is None
    assert "元数据损坏" in caplog.text or "空文本" in caplog.text
```

- [ ] **步骤 2：修改 `retrieval.py`**

在 `_merge_overlapping_results()` 中统计丢弃数，metrics 和 log：

```python
# 引入 MemoryBankMetrics 或使用已有 metrics 实例
# 在函数签名加 metrics 参数（通过 RetrievalPipeline.search 传入）

# 在 merge 循环中计数
dropped = 0
for members in groups.values():
    r = _merge_result_group(merging, members)
    if r is not None:
        merged.append(r)
    else:
        dropped += 1
if dropped:
    logger.warning("merge_overlapping_results: dropped %d groups (empty text)", dropped)
    metrics.forget_count += 1  # 复用 forget_count 统计丢弃事件
```

`RetrievalPipeline._merge_neighbors` 修改：`_merge_overlapping_results(merged_results)` → `_merge_overlapping_results(merged_results, metrics=self._metrics)`。`_merge_overlapping_results` 函数签名加 `metrics: MemoryBankMetrics | None = None` 参数。

修改 `app/memory/memory_bank/observability.py` — `forget_count` 字段注释加说明"也用于统计合并丢弃"。

- [ ] **步骤 3：commit**

```bash
git add app/memory/memory_bank/retrieval.py app/memory/memory_bank/observability.py
git commit -m "fix: log warning and track metrics when merge_overlapping_results drops groups"
```

---

### 任务 2.5：旧平铺迁移简化

**文件：**
- 修改：`app/storage/init_data.py`

**说明：**
每次启动扫描磁盘执行一次性迁移。加 `.migrated_flag` sentinel 文件跳过。

- [ ] **步骤 1：编写测试**

```python
# 追加到 tests/test_storage.py

def test_migration_skipped_with_flag(tmp_path):
    """存在迁移标记时跳过迁移。"""
    from app.storage.init_data import init_storage
    flag = tmp_path / ".migrated_flag"
    flag.write_text("1")
    # 应不报错、不创建额外文件
    init_storage(data_dir=tmp_path)
    assert flag.exists()
```

- [ ] **步骤 2：修改 `init_data.py`**

```python
_MIGRATED_FLAG = ".migrated_flag"

def init_storage(data_dir: Path | None = None) -> None:
    """初始化数据目录。存在标记时跳过迁移。"""
    root = data_dir or DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    flag = root / _MIGRATED_FLAG
    if flag.exists():
        logger.debug("Migration already completed, skipping")
        return
    # ... 原迁移逻辑 ...
    flag.write_text("1")  # 迁移完成后设标记
```

注意：`DATA_DIR` 从 `app.config` import，已在文件顶部定义。新增 `data_dir` 可选参数，默认 `None` 使用 `DATA_DIR`。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/test_storage.py -v`
预期：全部通过

- [ ] **步骤 4：commit**

```bash
git add app/storage/init_data.py
git commit -m "perf: skip legacy flat migration with sentinel flag file"
```

---

## 自检

- [ ] 规格覆盖：5 项全部有对应任务
- [ ] 占位符：无 TODO/TBD
- [ ] 类型一致：TypedDict key 名与 workflow.py 中使用的 key 一致
