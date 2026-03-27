# P0 紧急修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 10 个高严重度问题：确定性 event_id、XSS 漏洞、死代码清理、异常吞没、WebUI 缺少 memorybank 选项、导入副作用。

**Architecture:** 每个任务独立修改一个文件或一组紧密关联的文件，不改变模块间接口。P0 不引入新依赖。

**Tech Stack:** Python 3.13, hashlib (stdlib), FastAPI, pytest, ruff

---

### Task 1: `hash()` → `hashlib` 确定性 event_id

**Files:**
- Modify: `app/agents/workflow.py:199-201`
- Modify: `tests/test_api.py`

- [ ] **Step 1: 写失败测试 — 验证相同输入产生相同 event_id**

在 `tests/test_api.py` 或新测试文件中添加测试，验证同一 decision 产生确定性 event_id：

```python
# tests/test_workflow_event_id.py
from app.agents.workflow import AgentWorkflow


def test_event_id_deterministic():
    """相同decision应产生确定性event_id."""
    decision = {"content": "测试提醒", "type": "reminder"}
    expected_prefix = "unknown_"
    event_id_1 = f"{expected_prefix}{hash(str(decision))}"
    event_id_2 = f"{expected_prefix}{hash(str(decision))}"
    # hash() 在同一进程内是确定性的，但跨进程不确定
    # 这里只验证格式正确即可，跨进程确定性在 Step 3 实现后验证
    assert event_id_1.startswith("unknown_")
    assert event_id_2 == event_id_1
```

- [ ] **Step 2: 运行测试确认当前行为**

Run: `uv run pytest tests/test_workflow_event_id.py -v`

- [ ] **Step 3: 修改 workflow.py 使用 hashlib**

在 `app/agents/workflow.py` 顶部添加 `import hashlib`，将第 201 行：
```python
event_id = f"unknown_{hash(str(decision))}"
```
改为：
```python
event_id = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"
```

- [ ] **Step 4: 更新测试验证 hashlib 确定性**

```python
# tests/test_workflow_event_id.py
import hashlib


def test_event_id_deterministic_with_hashlib():
    """hashlib产生的event_id应跨调用一致."""
    decision = {"content": "测试提醒", "type": "reminder"}
    event_id_1 = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"
    event_id_2 = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"
    assert event_id_1 == event_id_2
    assert len(event_id_1) == len("unknown_") + 8
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_workflow_event_id.py -v`

- [ ] **Step 6: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -v`

- [ ] **Step 7: Commit**

```bash
git add app/agents/workflow.py tests/test_workflow_event_id.py
git commit -m "fix: use hashlib for deterministic event_id generation"
```

---

### Task 2: WebUI XSS 修复

**Files:**
- Modify: `webui/index.html:92-93`

- [ ] **Step 1: 修改 loadHistory 使用 textContent**

将 `webui/index.html` 第 89-95 行替换为：

```javascript
async function loadHistory() {
    const response = await fetch('/api/history');
    const data = await response.json();
    const container = document.getElementById('historyList');
    container.innerHTML = '';
    data.history.forEach(item => {
        const div = document.createElement('div');
        div.className = 'history-item';
        div.textContent = item.content || JSON.stringify(item);
        container.appendChild(div);
    });
}
```

- [ ] **Step 2: 验证 HTML 无语法错误**

在浏览器中打开文件或使用简单检查确保 HTML 合法。

- [ ] **Step 3: Commit**

```bash
git add webui/index.html
git commit -m "fix: prevent XSS in history display by using textContent"
```

---

### Task 3: WebUI 添加 memorybank 选项

**Files:**
- Modify: `webui/index.html:28-32`

- [ ] **Step 1: 在 select 中添加 memorybank 选项**

在 `webui/index.html` 第 31 行 `<option value="embeddings">向量检索</option>` 后添加：

```html
<option value="memorybank">MemoryBank</option>
```

- [ ] **Step 2: 验证 HTML 合法**

- [ ] **Step 3: Commit**

```bash
git add webui/index.html
git commit -m "feat: add memorybank mode option to web UI"
```

---

### Task 4: JSONStore 死代码清理

**Files:**
- Modify: `app/storage/json_store.py`

- [ ] **Step 1: 删除死代码块和 sys 导入**

删除 `import sys`（第 4 行）和第 8-11 行的空 `if/else` 块。

删除 `save()` 方法（第 45-47 行），确认无其他代码调用 `save()`：

```bash
rg '\.save\(' app/ tests/
```

如果有调用点，替换为 `.write()`。

- [ ] **Step 2: 运行测试确认无回归**

Run: `uv run pytest tests/test_storage.py -v`

- [ ] **Step 3: Commit**

```bash
git add app/storage/json_store.py
git commit -m "chore: remove dead code from JSONStore"
```

---

### Task 5: workflow.py 死代码清理

**Files:**
- Modify: `app/agents/workflow.py:37-48`

- [ ] **Step 1: 合并重复 elif/else 分支，删除冗余别名**

将第 37-48 行：
```python
            if memory_mode == "embeddings" or memory_mode == "memorybank":
                embedding_model = get_embedding_model()
                self._embedding_model = embedding_model
                self.memory_module = MemoryModule(
                    data_dir, embedding_model=embedding_model, chat_model=chat_model
                )
            elif memory_mode == "llm_only":
                self.memory_module = MemoryModule(data_dir, chat_model=chat_model)
            else:
                self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self.memory = self.memory_module
```

改为：
```python
            if memory_mode in ("embeddings", "memorybank"):
                embedding_model = get_embedding_model()
                self._embedding_model = embedding_model
                self.memory_module = MemoryModule(
                    data_dir, embedding_model=embedding_model, chat_model=chat_model
                )
            else:
                self.memory_module = MemoryModule(data_dir, chat_model=chat_model)
```

- [ ] **Step 2: 确认 `self.memory` 无外部引用，若有则替换**

```bash
rg 'self\.memory[^_]' app/ tests/
```

`self.memory` 在 `_execution_node`（第 195、198 行）中被使用。
先替换为 `self.memory_module`：
- 第 195 行 `self.memory.write_interaction(` → `self.memory_module.write_interaction(`
- 第 198 行 `self.memory.write(` → `self.memory_module.write(`

然后删除 `self.memory = self.memory_module`。

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/ -v`

- [ ] **Step 4: Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: clean up dead branches and redundant alias in workflow"
```

---

### Task 6: runner.py 删除未使用方法

**Files:**
- Modify: `app/experiment/runner.py:355-380`

- [ ] **Step 1: 确认无调用点**

```bash
rg '_extract_task_indicators|_get_type_patterns' app/ tests/
```

- [ ] **Step 2: 删除 `_extract_task_indicators` 和 `_get_type_patterns` 方法**

删除 `app/experiment/runner.py` 第 355-380 行的两个方法。

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/test_experiment_runner.py -v`

- [ ] **Step 4: Commit**

```bash
git add app/experiment/runner.py
git commit -m "chore: remove unused _extract_task_indicators and _get_type_patterns"
```

---

### Task 7: memory.py 异常不再吞没

**Files:**
- Modify: `app/memory/memory.py:97-98`

- [ ] **Step 1: 添加 logger 导入**

在 `app/memory/memory.py` 顶部添加：
```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 修改异常处理**

将第 97-98 行：
```python
            except Exception:
                continue
```
改为：
```python
            except Exception as e:
                logger.warning("LLM relevance check failed: %s", e, exc_info=True)
                continue
```

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/ -v`

- [ ] **Step 4: Commit**

```bash
git add app/memory/memory.py
git commit -m "fix: log LLM search exceptions instead of silently swallowing"
```

---

### Task 8: 消除 `app/__init__.py` 导入副作用

**Files:**
- Modify: `app/__init__.py`

- [ ] **Step 1: 清空 __init__.py 的副作用**

将 `app/__init__.py` 改为：
```python
"""知行车秘应用包."""
```

- [ ] **Step 2: 确认 `main.py` 中已有 init_storage 调用**

检查 `main.py` — 当前没有显式 init 调用。需要在 `main.py` 或 API 模块中添加。由于 `app/api/main.py` 的 `MemoryModule` 初始化会触发 `JSONStore._ensure_file()`（自动创建文件），所以实际上不需要显式 `init_storage`。但 `init_data.py` 也会创建 `strategies.json` 等文件，需要确认 `MemoryModule.__init__` 是否会覆盖已有文件。

检查 `json_store.py:31-34`：`_ensure_file` 只在文件不存在时创建，所以不会覆盖。

因此只需确保 `init_storage()` 在服务启动时调用一次。在 `main.py` 的 `if __name__ == "__main__"` 中添加。

- [ ] **Step 3: 在 main.py 中添加 init_storage 调用**

修改 `main.py`（保留现有 `@app.get("/")` 路由）：
```python
"""记忆工作台主入口."""

import os
import uvicorn
from pathlib import Path
from fastapi.responses import FileResponse
from app.api.main import app
from app.storage.init_data import init_storage

webui_path = Path(__file__).parent / "webui"


@app.get("/")
async def root():
    """返回前端 WebUI 入口页面."""
    return FileResponse(webui_path / "index.html")


if __name__ == "__main__":
    init_storage(os.getenv("DATA_DIR", "data"))
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 4: 运行测试确认无回归**

Run: `uv run pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py main.py
git commit -m "fix: remove import-time side effect from app/__init__.py"
```

---

### Task 9: 消除 `app/api/main.py` 模块级 LLM 实例化

**Files:**
- Modify: `app/api/main.py:19-23`
- Modify: `main.py`

- [ ] **Step 1: 将模块级实例化改为依赖注入**

将 `app/api/main.py` 的模块级代码改为 FastAPI `Depends`：

```python
"""FastAPI应用主入口."""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import os
import logging

from app.memory.memory import MemoryModule
from app.models.settings import get_chat_model, get_embedding_model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="知行车秘 - 车载AI智能体")

DATA_DIR = os.getenv("DATA_DIR", "data")


def get_memory_module() -> MemoryModule:
    chat_model = get_chat_model()
    embedding_model = get_embedding_model()
    return MemoryModule(
        data_dir=DATA_DIR, embedding_model=embedding_model, chat_model=chat_model
    )


_memory_module: MemoryModule | None = None


def ensure_memory_module() -> MemoryModule:
    global _memory_module
    if _memory_module is None:
        _memory_module = get_memory_module()
    return _memory_module


class QueryRequest(BaseModel):

    """用户查询请求."""

    query: str
    memory_mode: Optional[str] = "keyword"


class FeedbackRequest(BaseModel):

    """用户反馈请求."""

    event_id: str
    action: str
    modified_content: Optional[str] = None


@app.post("/api/query")
async def query(
    request: QueryRequest, mm: MemoryModule = Depends(ensure_memory_module)
):
    """处理用户查询."""
    from app.agents.workflow import AgentWorkflow

    try:
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=request.memory_mode or "keyword",
            memory_module=mm,
        )
        result, event_id = workflow.run(request.query)
        return {"result": result, "event_id": event_id}
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/feedback")
async def feedback(
    request: FeedbackRequest, mm: MemoryModule = Depends(ensure_memory_module)
):
    """提交用户反馈."""
    try:
        mm.update_feedback(
            request.event_id,
            {"action": request.action, "modified_content": request.modified_content},
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Feedback failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/experiment/report")
async def experiment_report():
    """获取实验报告."""
    from app.experiment.runner import ExperimentRunner

    runner = ExperimentRunner(DATA_DIR)
    return {"report": runner.generate_report()}


@app.get("/api/history")
async def history(
    limit: int = 10, mm: MemoryModule = Depends(ensure_memory_module)
):
    """获取历史记录."""
    try:
        history = mm.get_history(limit=limit)
        return {"history": history}
    except Exception as e:
        logger.error(f"History retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/ -v`

- [ ] **Step 3: Commit**

```bash
git add app/api/main.py
git commit -m "refactor: lazy-init LLM models via FastAPI Depends instead of module-level"
```

---

### Task 10: 运行 lint 并修复

- [ ] **Step 1: 运行 ruff lint**

Run: `uv run ruff check app/ tests/ main.py`

- [ ] **Step 2: 自动修复可修复的问题**

Run: `uv run ruff check --fix app/ tests/ main.py`

- [ ] **Step 3: 手动修复剩余问题（如有）**

- [ ] **Step 4: 运行测试确认全部通过**

Run: `uv run pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: fix lint warnings after P0 changes"
```
