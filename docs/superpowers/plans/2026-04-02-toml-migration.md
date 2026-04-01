# TOML 存储迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将配置文件和记忆存储从 JSON 格式迁移至 TOML 格式

**Architecture:** 新增 TOMLStore 类替代 JSONStore，统一使用 .toml 扩展名，数据结构通过 tomli-w 写入，tomllib 读取。

**Tech Stack:** Python 3.11+, tomllib (标准库), tomli-w

---

## 文件结构

| 文件 | 变更 |
|------|------|
| `app/storage/toml_store.py` | 新增 - TOMLStore 实现 |
| `app/storage/json_store.py` | 删除 |
| `app/storage/init_data.py` | 修改 - .toml 扩展名和格式 |
| `app/storage/__init__.py` | 修改 - 导出 TOMLStore |
| `app/agents/workflow.py` | 修改 - TOMLStore, .toml |
| `app/memory/components.py` | 修改 - TOMLStore, .toml |
| `app/memory/stores/memory_bank_store.py` | 修改 - TOMLStore |
| `app/models/settings.py` | 修改 - 默认 .toml 路径 |
| `adapters/model_config.py` | 修改 - 默认 .toml 路径 |
| `tests/test_components.py` | 修改 - TOMLStore |
| `tests/test_storage.py` | 修改 - TOMLStore |
| `tests/test_model_config.py` | 修改 - .toml |
| `tests/test_settings.py` | 修改 - .toml |

---

## Task 0: 安装依赖

- [ ] **Step 1: 安装 tomli-w**

```bash
pip install tomli-w
```

或添加到 pyproject.toml 依赖中。

- [ ] **Step 2: 提交**

```bash
git add -A && git commit -m "chore: add tomli-w dependency for TOML storage"
```

---

## Task 1: 创建 TOMLStore 类

**Files:**
- Create: `app/storage/toml_store.py`
- Reference: `app/storage/json_store.py`

- [ ] **Step 1: 创建 toml_store.py**

```python
"""TOML文件存储后端，支持列表和字典类型的读写操作."""

import asyncio
import tomllib
from pathlib import Path
from typing import Any, Callable, TypeVar

import aiofiles
import tomli_w

T = TypeVar("T")

_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}
_LOCK_REGISTRY_LOCK = asyncio.Lock()


def _get_file_lock(filepath: Path) -> asyncio.Lock:
    """获取文件路径对应的锁，实现跨实例共享."""
    key = str(filepath.resolve())
    return _LOCK_REGISTRY.setdefault(key, asyncio.Lock())


class TOMLStore:
    """基于TOML文件的通用存储引擎."""

    def __init__(
        self,
        data_dir: Path,
        filename: Path,
        default_factory: Callable[[], T] = lambda: dict(),
    ) -> None:
        """初始化TOML存储，指定数据目录和文件名."""
        self.filepath = filename if filename.is_absolute() else data_dir / filename
        self.default_factory: Callable[[], T] = default_factory
        self._lock = _get_file_lock(self.filepath)

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            with self.filepath.open("wb") as f:
                tomli_w.dump(self.default_factory(), f)

    async def _async_write(self, data: T) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.filepath, "wb") as f:
            await f.write(tomli_w.dumps(data))

    async def _read_unsafe(self) -> T:
        """读操作，不获取锁（调用方必须持有锁）."""
        if not await asyncio.to_thread(self.filepath.exists):
            await asyncio.to_thread(self._ensure_file)
        async with aiofiles.open(self.filepath, "rb") as f:
            content = await f.read()
        return tomllib.loads(content.decode("utf-8"))

    async def read(self) -> T:
        """读取TOML文件中的全部数据."""
        async with self._lock:
            return await self._read_unsafe()

    async def write(self, data: T) -> None:
        """写入数据到TOML文件."""
        async with self._lock:
            await self._async_write(data)

    async def append(self, item: Any) -> None:  # noqa: ANN401
        """向列表类型存储追加一个元素."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, list):
                raise TypeError(
                    f"append() requires list factory, got {type(data).__name__}"
                )
            data.append(item)
            await self._async_write(data)

    async def update(self, key: str, value: Any) -> None:  # noqa: ANN401
        """更新字典类型存储中指定键的值."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, dict):
                raise TypeError(
                    f"update() requires dict factory, got {type(data).__name__}"
                )
            data[key] = value
            await self._async_write(data)
```

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/storage/toml_store.py --fix`
Expected: 无错误

- [ ] **Step 3: 运行 ty check**

Run: `uv run ty check app/storage/toml_store.py`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add app/storage/toml_store.py
git commit -m "feat: add TOMLStore for TOML-based storage"
```

---

## Task 2: 更新 init_data.py

**Files:**
- Modify: `app/storage/init_data.py:19-41`

- [ ] **Step 1: 修改 init_data.py 扩展名和格式**

将所有 `.json` 改为 `.toml`，并更新数据结构为 TOML 格式。

主要变更：
- `json.dump` → `tomli_w.dump`
- 扩展名从 .json 改为 .toml
- 导入改为 `tomllib` 和 `tomli_w`

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/storage/init_data.py --fix`

- [ ] **Step 3: 运行 ty check**

Run: `uv run ty check app/storage/init_data.py`

- [ ] **Step 4: 提交**

```bash
git add app/storage/init_data.py
git commit -m "feat: migrate init_data.py to TOML format"
```

---

## Task 3: 更新 agents/workflow.py

**Files:**
- Modify: `app/agents/workflow.py:16,51`

- [ ] **Step 1: 修改导入和扩展名**

- `from app.storage.json_store import JSONStore` → `from app.storage.toml_store import TOMLStore`
- `JSONStore(data_dir, Path("strategies.json"), dict)` → `TOMLStore(data_dir, Path("strategies.toml"), dict)`

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/agents/workflow.py --fix`

- [ ] **Step 3: 提交**

```bash
git add app/agents/workflow.py
git commit -m "feat: migrate workflow.py to TOMLStore"
```

---

## Task 4: 更新 memory/components.py

**Files:**
- Modify: `app/memory/components.py:14,37,87,100,162,167`

- [ ] **Step 1: 修改所有 JSONStore 引用**

- `from app.storage.json_store import JSONStore` → `from app.storage.toml_store import TOMLStore`
- 所有 `.json` 扩展名改为 `.toml`

具体变更点：
- Line 37: `events.json` → `events.toml`
- Line 87: `strategies.json` → `strategies.toml`
- Line 100: `feedback.json` → `feedback.toml`
- Line 162: `interactions.json` → `interactions.toml`
- Line 167: `memorybank_summaries.json` → `memorybank_summaries.toml`

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/memory/components.py --fix`

- [ ] **Step 3: 提交**

```bash
git add app/memory/components.py
git commit -m "feat: migrate memory/components.py to TOMLStore"
```

---

## Task 5: 更新 memory/stores/memory_bank_store.py

**Files:**
- Modify: `app/memory/stores/memory_bank_store.py:8`

- [ ] **Step 1: 修改导入**

- `from app.storage.json_store import JSONStore` → `from app.storage.toml_store import TOMLStore`

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/memory/stores/memory_bank_store.py --fix`

- [ ] **Step 3: 提交**

```bash
git add app/memory/stores/memory_bank_store.py
git commit -m "feat: migrate memory_bank_store.py to TOMLStore"
```

---

## Task 6: 更新 settings.py 和 model_config.py

**Files:**
- Modify: `app/models/settings.py:97`
- Modify: `adapters/model_config.py:19`

- [ ] **Step 1: 修改默认配置路径**

- `app/models/settings.py:97`: `"config/llm.json"` → `"config/llm.toml"`
- `adapters/model_config.py:19`: `"config/llm.json"` → `"config/llm.toml"`

- [ ] **Step 2: 运行 ruff check**

Run: `uv run ruff check app/models/settings.py adapters/model_config.py --fix`

- [ ] **Step 3: 提交**

```bash
git add app/models/settings.py adapters/model_config.py
git commit -m "feat: update default config path to .toml"
```

---

## Task 7: 更新测试文件

**Files:**
- Modify: `tests/test_components.py:159-217`
- Modify: `tests/test_storage.py:26-61`
- Modify: `tests/test_model_config.py:23,50,84,108`
- Modify: `tests/test_settings.py:79,130,140,172,422`

- [ ] **Step 1: 修改 test_components.py**

- `from app.storage.json_store import JSONStore` → `from app.storage.toml_store import TOMLStore`
- `Path("strategies.json")` → `Path("strategies.toml")`
- `Path("feedback.json")` → `Path("feedback.toml")`

- [ ] **Step 2: 修改 test_storage.py**

- 同上修改

- [ ] **Step 3: 修改 test_model_config.py**

- `tmp_path / "llm.json"` → `tmp_path / "llm.toml"`

- [ ] **Step 4: 修改 test_settings.py**

- `tmp_path / "config" / "llm.json"` → `tmp_path / "config" / "llm.toml"`
- `tmp_path / "nonexistent.json"` → `tmp_path / "nonexistent.toml"`

- [ ] **Step 5: 运行 ruff check**

Run: `uv run ruff check tests/ --fix`

- [ ] **Step 6: 提交**

```bash
git add tests/
git commit -m "test: migrate test files to TOML"
```

---

## Task 8: 删除 json_store.py

**Files:**
- Delete: `app/storage/json_store.py`

- [ ] **Step 1: 确认所有 JSONStore 引用已移除**

Run: `grep -r "json_store" app/ --include="*.py"`
Expected: 无结果

- [ ] **Step 2: 删除文件**

```bash
git rm app/storage/json_store.py
```

- [ ] **Step 3: 提交**

```bash
git commit -m "feat: remove JSONStore, replaced by TOMLStore"
```

---

## Task 9: 验证和清理

- [ ] **Step 1: 运行完整 lint 和 typecheck**

```bash
uv run ruff check --fix && uv run ty check && uv run ruff format
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest
```

- [ ] **Step 3: 删除旧 .json 文件**

确认测试通过后：

```bash
rm -f config/*.json data/*.json
```

- [ ] **Step 4: 提交清理**

```bash
git add -A && git commit -m "chore: remove legacy JSON files after TOML migration"
```

---

## 执行选项

**1. Subagent-Driven (recommended)** - 任务逐个执行，任务间 review

**2. Inline Execution** - 在当前 session 批量执行
