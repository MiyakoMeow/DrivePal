# vendor_adapter 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `runner.py`（731行）拆分为 Strategy Pattern 架构，使新增 memory_type 只需添加一个文件。

**Architecture:** 统一 MemoryStrategy Protocol + QueryEvaluator Protocol，将每文件初始化与每查询评估分离。所有 memory_type 通过 STRATEGIES 注册表分发。

**Tech Stack:** Python 3.14, asyncio, aiofiles, pytest

**Spec:** `docs/superpowers/specs/2026-04-13-vendor-adapter-refactor-design.md`

---

## 文件结构映射

```
vendor_adapter/VehicleMemBench/
├── __init__.py              # 不变
├── model_config.py          # 不变
├── paths.py                 # 新建：从 runner.py 提取路径常量 + sys.path 设置
├── loader.py                # 新建：从 runner.py 提取数据加载函数
├── strategies/
│   ├── __init__.py          # 新建：Protocol + STRATEGIES + VehicleMemBenchError
│   ├── common.py            # 新建：从 memory_adapters/common.py 迁移
│   ├── none.py              # 新建：NoneStrategy
│   ├── gold.py              # 新建：GoldStrategy
│   ├── kv.py                # 新建：KvMemoryStrategy
│   └── memory_bank.py       # 新建：从 memory_adapters/memory_bank_adapter.py + runner.py 合并
├── runner.py                # 重写：精简为编排逻辑 + 重导出
└── reporter.py              # 新建：从 runner.py 提取报告逻辑
```

---

### Task 1: 创建 `paths.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/paths.py`
- Test: `tests/test_vendor_adapter/test_runner.py`（后续 Task 10 调整）

- [ ] **Step 1: 创建 `paths.py`**

从 `runner.py` 提取路径常量和 sys.path 设置：

```python
"""路径常量与 sys.path 初始化."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "VehicleMemBench"
BENCHMARK_DIR = VENDOR_DIR / "benchmark"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark"


def setup_vehiclemembench_path() -> None:
    """将 VehicleMemBench 路径添加到 sys.path."""
    for d in [VENDOR_DIR, VENDOR_DIR / "evaluation"]:
        d_str = str(d)
        if not any(Path(p).resolve() == Path(d_str).resolve() for p in sys.path):
            sys.path.insert(0, d_str)


setup_vehiclemembench_path()


def ensure_output_dir() -> Path:
    """确保输出目录存在并返回路径."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def file_output_dir(memory_type: str, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的输出目录路径."""
    return OUTPUT_DIR / memory_type / f"file_{file_num}"


def prep_path(memory_type: str, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的 prep 数据路径."""
    return file_output_dir(memory_type, file_num) / "prep.json"


def query_result_path(memory_type: str, file_num: int, event_index: int) -> Path:
    """返回指定记忆类型、文件编号和事件索引的查询结果路径."""
    return file_output_dir(memory_type, file_num) / f"query_{event_index}.json"
```

- [ ] **Step 2: 在 `runner.py` 顶部添加 `paths.py` 导入，验证无破坏**

在 `runner.py` 顶部添加：
```python
from .paths import (  # noqa: F401 — 重导出以保持公共 API
    BENCHMARK_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    VENDOR_DIR,
    ensure_output_dir,
    file_output_dir,
    prep_path,
    query_result_path,
    setup_vehiclemembench_path,
)
```

运行：`uv run pytest tests/test_vendor_adapter/ -v`
预期：所有测试通过（重导出保持 API 不变）

- [ ] **Step 3: 提交**

```bash
git add vendor_adapter/VehicleMemBench/paths.py vendor_adapter/VehicleMemBench/runner.py
git commit -m "refactor: extract paths.py from runner.py"
```

---

### Task 2: 创建 `loader.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/loader.py`
- Modify: `vendor_adapter/VehicleMemBench/runner.py`

- [ ] **Step 1: 创建 `loader.py`**

```python
"""QA/历史/prep 数据加载."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from .paths import BENCHMARK_DIR
from .strategies import MemoryStrategy

if TYPE_CHECKING:
    from vendor_adapter.VehicleMemBench import BenchMemoryMode

logger = logging.getLogger(__name__)


async def load_qa(file_num: int) -> dict:
    """加载 QA JSON 数据."""
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return json.loads(await f.read())


async def load_history(file_num: int) -> str:
    """加载历史文本."""
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


async def load_qa_safe(fnum: int) -> tuple[int, dict | None]:
    """安全加载 QA 数据，缺失时返回 (fnum, None)."""
    try:
        return fnum, await load_qa(fnum)
    except FileNotFoundError:
        logger.warning("[warn] qa file %d not found", fnum)
        return fnum, None


async def load_history_cache(
    file_nums: list[int],
    strategies: list[MemoryStrategy],
) -> dict[int, str]:
    """批量加载历史，按 needs_history 过滤."""
    need_history = any(s.needs_history() for s in strategies)
    if not need_history:
        return {}

    async def _load_or_empty(fnum: int) -> tuple[int, str]:
        try:
            return fnum, await load_history(fnum)
        except FileNotFoundError:
            logger.warning("[warn] history file %d not found, using empty", fnum)
            return fnum, ""

    import asyncio

    history_pairs = await asyncio.gather(*(_load_or_empty(f) for f in file_nums))
    return dict(history_pairs)


async def load_prep(
    fnum: int,
    mtype: BenchMemoryMode,
) -> tuple[BenchMemoryMode, int, dict | None]:
    """加载单个 prep 数据."""
    from vendor_adapter.VehicleMemBench import BenchMemoryMode as _BMM

    _PREP_FREE_TYPES: frozenset[_BMM] = frozenset({_BMM.NONE, _BMM.GOLD})
    if mtype in _PREP_FREE_TYPES:
        return mtype, fnum, {"type": mtype}
    pp = prep_path_func(mtype, fnum)
    try:
        async with aiofiles.open(pp, encoding="utf-8") as f:
            return mtype, fnum, json.loads(await f.read())
    except FileNotFoundError:
        return mtype, fnum, None
    except json.JSONDecodeError:
        logger.warning(
            "[warn] corrupt prep file for %s file %d, skipping",
            mtype,
            fnum,
        )
        return mtype, fnum, None


async def load_prep_cache(
    file_nums: list[int],
    types: list[BenchMemoryMode],
) -> dict[tuple[BenchMemoryMode, int], dict | None]:
    """批量加载 prep 数据缓存."""
    import asyncio

    prep_raw = await asyncio.gather(
        *(load_prep(f, t) for f in file_nums for t in types),
    )
    return {(mt, fn): data for mt, fn, data in prep_raw}


def prep_path_func(mtype: BenchMemoryMode, fnum: int) -> Path:
    """返回 prep 路径（避免循环导入的桥接函数）."""
    from .paths import prep_path

    return prep_path(mtype, fnum)
```

**注意：** `load_prep` 内的 `_PREP_FREE_TYPES` 是临时兼容代码，Task 9 重写 runner 后通过 strategy 判断替代。

- [ ] **Step 2: 在 `runner.py` 中导入 loader，替换内部函数**

将 `runner.py` 中的 `_load_qa`, `_load_history`, `_load_qa_safe`, `_load_history_cache`, `_load_prep`, `_load_prep_cache` 替换为 loader 导入。

- [ ] **Step 3: 运行测试**

运行：`uv run pytest tests/test_vendor_adapter/ -v`
预期：所有测试通过

- [ ] **Step 4: 提交**

```bash
git add vendor_adapter/VehicleMemBench/loader.py vendor_adapter/VehicleMemBench/runner.py
git commit -m "refactor: extract loader.py from runner.py"
```

---

### Task 3: 创建 `strategies/__init__.py` — Protocol + 注册表

**Files:**
- Create: `vendor_adapter/VehicleMemBench/strategies/__init__.py`
- Delete: `vendor_adapter/VehicleMemBench/memory_adapters/__init__.py`（Task 8 后）

- [ ] **Step 1: 创建 `strategies/__init__.py`**

```python
"""统一记忆策略 Protocol 与注册表."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from vendor_adapter.VehicleMemBench import BenchMemoryMode

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

    from evaluation.agent_client import AgentClient


class VehicleMemBenchError(Exception):
    """VehicleMemBench 模块的基准错误."""


@runtime_checkable
class QueryEvaluator(Protocol):
    """每文件评估器（含一次性初始化资源）."""

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        """评估单个 query."""
        ...


@runtime_checkable
class MemoryStrategy(Protocol):
    """统一记忆策略接口."""

    @property
    def mode(self) -> BenchMemoryMode: ...

    def needs_history(self) -> bool:
        """prepare 阶段是否需要历史文本."""
        ...

    def needs_agent_for_prep(self) -> bool:
        """prepare 阶段是否需要 agent client."""
        ...

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        """准备阶段：返回 prep 数据字典（序列化为 prep.json）."""
        ...

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> QueryEvaluator:
        """创建每文件评估器."""
        ...
```

- [ ] **Step 2: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/__init__.py
git commit -m "refactor: add MemoryStrategy and QueryEvaluator protocols"
```

---

### Task 4: 迁移 `strategies/common.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/strategies/common.py`

- [ ] **Step 1: 创建 `strategies/common.py`**

内容从 `vendor_adapter/VehicleMemBench/memory_adapters/common.py` 复制，保持完全一致：

```python
"""记忆适配器通用工具函数."""

import re
from typing import TYPE_CHECKING

from app.memory.schemas import MemoryEvent, SearchResult

if TYPE_CHECKING:
    from app.memory.interfaces import MemoryStore


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    """将历史文本转换为交互记录."""
    if not history_text.strip():
        return []
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+(.+)$")
    records = []
    for i, raw_line in enumerate(history_text.strip().splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            date_group = m.group(1)
            content = m.group(2)
        else:
            date_group = "unknown"
            content = line
        records.append(
            MemoryEvent(
                id=f"hist_{i}",
                content=content,
                description=content,
                type="general",
                date_group=date_group,
                memory_strength=1,
            ),
        )
    return records


def format_search_results(results: list[SearchResult]) -> tuple[str, int]:
    """将搜索结果格式化为文本和数量."""
    if not results:
        return ("", 0)
    texts = []
    for r in results:
        event = r.event if hasattr(r, "event") else r
        if isinstance(event, dict):
            content = event.get("content", "")
        elif hasattr(event, "content"):
            content = event.content
        else:
            content = str(event)
        if content:
            texts.append(content)
    return ("\n".join(texts), len(texts))


class StoreClient:
    """用于在记忆存储中搜索的客户端."""

    def __init__(self, store: MemoryStore) -> None:
        """使用存储实例初始化."""
        self.store = store

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """在存储中搜索相关结果."""
        return await self.store.search(query=query, top_k=top_k)
```

- [ ] **Step 2: 更新 `test_common.py` 的 import 路径**

将 `from vendor_adapter.VehicleMemBench.memory_adapters.common import (` 改为 `from vendor_adapter.VehicleMemBench.strategies.common import (`。

- [ ] **Step 3: 运行测试**

运行：`uv run pytest tests/test_vendor_adapter/test_common.py -v`
预期：通过

- [ ] **Step 4: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/common.py tests/test_vendor_adapter/test_common.py
git commit -m "refactor: migrate common.py to strategies/common.py"
```

---

### Task 5: 创建 `strategies/none.py` 和 `strategies/gold.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/strategies/none.py`
- Create: `vendor_adapter/VehicleMemBench/strategies/gold.py`

- [ ] **Step 1: 创建 `none.py`**

```python
"""无记忆策略."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.strategies import QueryEvaluator

if TYPE_CHECKING:
    import asyncio as _asyncio
    from concurrent.futures import Future

    from evaluation.agent_client import AgentClient

from evaluation.model_evaluation import process_task_direct


class _NoneEvaluator:
    """None 模式评估器：不使用历史文本."""

    def __init__(
        self,
        agent_client: AgentClient,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        self._agent_client = agent_client
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_direct,
                {**task, "history_text": ""},
                task_id,
                self._agent_client,
                self._reflect_num,
            )


class NoneStrategy:
    """无记忆策略：直接调用，不使用任何记忆."""

    @property
    def mode(self) -> BenchMemoryMode:
        return BenchMemoryMode.NONE

    def needs_history(self) -> bool:
        return False

    def needs_agent_for_prep(self) -> bool:
        return False

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        return None

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> _NoneEvaluator:
        return _NoneEvaluator(agent_client, reflect_num, query_semaphore)
```

- [ ] **Step 2: 创建 `gold.py`**

```python
"""黄金记忆策略."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.strategies import QueryEvaluator

if TYPE_CHECKING:
    import asyncio as _asyncio

    from evaluation.agent_client import AgentClient

from evaluation.model_evaluation import process_task_direct


class _GoldEvaluator:
    """Gold 模式评估器：使用黄金记忆文本."""

    def __init__(
        self,
        agent_client: AgentClient,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        self._agent_client = agent_client
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_direct,
                {**task, "history_text": gold_memory},
                task_id,
                self._agent_client,
                self._reflect_num,
            )


class GoldStrategy:
    """黄金记忆策略：直接注入 gold_memory 作为历史."""

    @property
    def mode(self) -> BenchMemoryMode:
        return BenchMemoryMode.GOLD

    def needs_history(self) -> bool:
        return False

    def needs_agent_for_prep(self) -> bool:
        return False

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        return None

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> _GoldEvaluator:
        return _GoldEvaluator(agent_client, reflect_num, query_semaphore)
```

- [ ] **Step 3: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/none.py vendor_adapter/VehicleMemBench/strategies/gold.py
git commit -m "refactor: add NoneStrategy and GoldStrategy"
```

---

### Task 6: 创建 `strategies/kv.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/strategies/kv.py`

- [ ] **Step 1: 创建 `kv.py`**

```python
"""键值记忆策略."""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from vendor_adapter.VehicleMemBench import BenchMemoryMode

if TYPE_CHECKING:
    from evaluation.agent_client import AgentClient

from evaluation.model_evaluation import (
    MemoryStore as VMBMemoryStore,
)
from evaluation.model_evaluation import (
    build_memory_key_value,
    process_task_with_kv_memory,
    split_history_by_day,
)

logger = logging.getLogger(__name__)


class _KvEvaluator:
    """KV 模式评估器：使用预构建的 KV 存储."""

    def __init__(
        self,
        agent_client: AgentClient,
        kv_store: VMBMemoryStore,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        self._agent_client = agent_client
        self._kv_store = kv_store
        self._reflect_num = reflect_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        async with self._semaphore:
            return await asyncio.to_thread(
                process_task_with_kv_memory,
                task,
                task_id,
                self._kv_store,
                self._agent_client,
                self._reflect_num,
            )


class KvMemoryStrategy:
    """键值记忆策略：提取历史中的 KV 对，用于查询评估."""

    @property
    def mode(self) -> BenchMemoryMode:
        return BenchMemoryMode.KV

    def needs_history(self) -> bool:
        return True

    def needs_agent_for_prep(self) -> bool:
        return True

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        if agent_client is None:
            return None
        daily = split_history_by_day(history_text)
        async with semaphore:
            store, _, _ = await asyncio.to_thread(
                build_memory_key_value,
                agent_client,
                daily,
            )
        return {"type": BenchMemoryMode.KV, "store": store.to_dict()}

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> _KvEvaluator:
        store = VMBMemoryStore()
        store.store = prep_data.get("store", {})
        return _KvEvaluator(agent_client, store, reflect_num, query_semaphore)
```

- [ ] **Step 2: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/kv.py
git commit -m "refactor: add KvMemoryStrategy"
```

---

### Task 7: 创建 `strategies/memory_bank.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/strategies/memory_bank.py`

- [ ] **Step 1: 创建 `memory_bank.py`**

```python
"""记忆库策略：结合嵌入向量和 LLM 的记忆搜索."""

import asyncio
import logging
import os
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING

from app.memory.stores.memory_bank import MemoryBankStore
from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.strategies.common import (
    StoreClient,
    format_search_results,
    history_to_interaction_records,
)
from vendor_adapter.VehicleMemBench.model_config import (
    get_store_chat_model,
    get_store_embedding_model,
)

if TYPE_CHECKING:
    from evaluation.agent_client import AgentClient

from evaluation.model_evaluation import (
    _run_vehicle_task_evaluation,
    get_list_module_tools_schema,
)

logger = logging.getLogger(__name__)

try:
    _SEARCH_TIMEOUT = int(os.environ.get("BENCHMARK_SEARCH_TIMEOUT", str(12 * 3600)))
except ValueError:
    _SEARCH_TIMEOUT = 12 * 3600

_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION = (
    "You are an intelligent in-car AI assistant responsible for fulfilling user requests by calling the vehicle system API.\n"
    "You have access to a memory store containing user vehicle preferences.\n"
    "- Use memory_search(query, top_k) to look up relevant user preferences\n"
    "- Use list_module_tools(module_name='xxx') to discover available functions\n"
    "- Call the specific functions you need\n"
    "When the available information does not support setting a device to a specific value, "
    "perform only the minimal required action."
)

_CUSTOM_ADAPTER_INITIAL_TOOLS = [
    {"type": "function", "function": get_list_module_tools_schema()},
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search user vehicle preferences by keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def _make_sync_memory_search(
    search_client: StoreClient,
) -> ...:
    """为同步 vendor 代码创建同步的 memory_search 包装器."""
    loop = asyncio.get_running_loop()

    def _search(query: str, top_k: int = 5) -> dict:
        future: Future | None = None
        try:
            future = asyncio.run_coroutine_threadsafe(
                search_client.search(query=query, top_k=top_k),
                loop,
            )
            results = future.result(timeout=_SEARCH_TIMEOUT)
        except TimeoutError:
            if future is not None:
                future.cancel()
            logger.warning("  [warn] memory_search timeout: %r", query)
            return {
                "success": False,
                "error": "search timed out",
                "results": "",
                "count": 0,
            }
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                logger.warning("  [warn] memory_search: event loop error: %s", e)
                return {"success": False, "error": str(e), "results": "", "count": 0}
            raise
        except OSError as e:
            logger.warning("  [warn] memory_search failed: %s", e)
            return {"success": False, "error": str(e), "results": "", "count": 0}
        else:
            text, count = format_search_results(results)
            return {"success": True, "results": text, "count": count}

    return _search


class _MemoryBankEvaluator:
    """记忆库评估器：使用预构建的搜索客户端."""

    def __init__(
        self,
        agent_client: AgentClient,
        search_client: StoreClient,
        reflect_num: int,
        file_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        self._agent_client = agent_client
        self._search_client = search_client
        self._reflect_num = reflect_num
        self._file_num = file_num
        self._semaphore = query_semaphore

    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        memory_funcs = {
            "memory_search": _make_sync_memory_search(self._search_client),
        }
        async with self._semaphore:
            return await asyncio.to_thread(
                _run_vehicle_task_evaluation,
                task=task,
                task_id=task_id,
                agent_client=self._agent_client,
                reflect_num=self._reflect_num,
                system_instruction=_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION,
                request_context=f"{BenchMemoryMode.MEMORY_BANK} file {self._file_num} task {task_id}",
                initial_tools=_CUSTOM_ADAPTER_INITIAL_TOOLS,
                memory_funcs=memory_funcs,
            )


class MemoryBankStrategy:
    """记忆库策略：使用嵌入向量 + LLM 构建可搜索的记忆存储."""

    @property
    def mode(self) -> BenchMemoryMode:
        return BenchMemoryMode.MEMORY_BANK

    def needs_history(self) -> bool:
        return True

    def needs_agent_for_prep(self) -> bool:
        return False

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        store_dir = output_dir / "store"
        async with semaphore:
            store_dir.mkdir(parents=True, exist_ok=True)
            chat_model = get_store_chat_model()
            embedding_model = get_store_embedding_model()
            store = MemoryBankStore(
                data_dir=store_dir,
                chat_model=chat_model,
                embedding_model=embedding_model,
            )
            for record in history_to_interaction_records(history_text):
                await store.write(record)
        return {"type": BenchMemoryMode.MEMORY_BANK, "data_dir": str(store_dir)}

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> _MemoryBankEvaluator:
        data_dir = Path(prep_data["data_dir"])
        chat_model = get_store_chat_model()
        embedding_model = get_store_embedding_model()
        store = await asyncio.to_thread(
            MemoryBankStore,
            data_dir=data_dir,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        search_client = StoreClient(store)
        return _MemoryBankEvaluator(
            agent_client, search_client, reflect_num, file_num, query_semaphore,
        )
```

**注意：** `_make_sync_memory_search` 的返回类型标注在实际实现时使用 `Callable[[str, int], dict]`。

- [ ] **Step 2: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/memory_bank.py
git commit -m "refactor: add MemoryBankStrategy"
```

---

### Task 8: 完善 `strategies/__init__.py` — 注册所有策略

**Files:**
- Modify: `vendor_adapter/VehicleMemBench/strategies/__init__.py`

- [ ] **Step 1: 在 `strategies/__init__.py` 底部添加注册表**

```python
from vendor_adapter.VehicleMemBench.strategies.gold import GoldStrategy
from vendor_adapter.VehicleMemBench.strategies.kv import KvMemoryStrategy
from vendor_adapter.VehicleMemBench.strategies.memory_bank import MemoryBankStrategy
from vendor_adapter.VehicleMemBench.strategies.none import NoneStrategy

STRATEGIES: dict[BenchMemoryMode, MemoryStrategy] = {
    s.mode: s
    for s in [NoneStrategy(), GoldStrategy(), KvMemoryStrategy(), MemoryBankStrategy()]
}
```

- [ ] **Step 2: 提交**

```bash
git add vendor_adapter/VehicleMemBench/strategies/__init__.py
git commit -m "refactor: register all strategies in STRATEGIES dict"
```

---

### Task 9: 创建 `reporter.py`

**Files:**
- Create: `vendor_adapter/VehicleMemBench/reporter.py`

- [ ] **Step 1: 创建 `reporter.py`**

从 `runner.py` 的 `_collect_results`, `_build_report_metrics`, `_compute_memory_scores`, `report` 提取：

```python
"""基准测试结果收集与报告生成."""

import json
import logging
from pathlib import Path

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.model_config import get_benchmark_config
from vendor_adapter.VehicleMemBench.paths import ensure_output_dir

logger = logging.getLogger(__name__)

from evaluation.model_evaluation import _build_metric


def collect_results(
    output_dir: Path,
) -> tuple[dict[BenchMemoryMode, list[dict]], dict[BenchMemoryMode, int]]:
    """从输出目录收集评估结果."""
    all_results: dict[BenchMemoryMode, list[dict]] = {}
    failed_counts: dict[BenchMemoryMode, int] = {}
    for path in sorted(output_dir.glob("*/*/query_*.json")):
        try:
            mtype = BenchMemoryMode(path.parent.parent.name)
        except ValueError:
            continue
        data: dict | None = None
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError, OSError:
            logger.warning("无法解析结果文件: %s", path)
            failed_counts[mtype] = failed_counts.get(mtype, 0) + 1
        if not isinstance(data, dict):
            continue
        if data.get("failed"):
            failed_counts[mtype] = failed_counts.get(mtype, 0) + 1
            continue
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].append(data)
    return all_results, failed_counts


def build_report_metrics(
    all_results: dict[BenchMemoryMode, list[dict]],
) -> dict[BenchMemoryMode, dict]:
    """构建评估报告指标."""
    cfg = get_benchmark_config()
    report_data: dict[BenchMemoryMode, dict] = {}
    for mtype, results in all_results.items():
        metric = _build_metric(results, model=cfg.model, memory_type=mtype)
        report_data[mtype] = metric
    return report_data


def compute_memory_scores(report_data: dict[BenchMemoryMode, dict]) -> None:
    """计算相对于 GOLD 的 memory_score."""
    gold_esm = report_data.get(BenchMemoryMode.GOLD, {}).get("exact_match_rate", 0)
    if gold_esm <= 0:
        return
    for mtype, metric in report_data.items():
        if mtype != BenchMemoryMode.GOLD:
            auto_esm = metric.get("exact_match_rate", 0)
            metric["memory_score"] = auto_esm / gold_esm


def report(output_path: Path | None = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = ensure_output_dir()
    all_results, failed_counts = collect_results(output_dir)
    report_data = build_report_metrics(all_results)

    for mtype, fc in failed_counts.items():
        metric = report_data.setdefault(mtype, {"total_failed": 0})
        metric["total_failed"] = fc

    compute_memory_scores(report_data)

    out = output_path if output_path is not None else output_dir / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    logger.info("Report written to %s", out)

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        failed = metric.get("total_failed", 0)
        logger.info(
            "  %s: ESM=%s, F-F1=%s, V-F1=%s, Calls=%s%s",
            mtype,
            f"{esm:.2%}",
            f"{metric.get('state_f1_positive', 0):.4f}",
            f"{metric.get('state_f1_change', 0):.4f}",
            f"{metric.get('avg_pred_calls', 0):.1f}",
            f", Failed={failed}" if failed else "",
        )
```

- [ ] **Step 2: 提交**

```bash
git add vendor_adapter/VehicleMemBench/reporter.py
git commit -m "refactor: extract reporter.py from runner.py"
```

---

### Task 10: 重写 `runner.py`

**Files:**
- Modify: `vendor_adapter/VehicleMemBench/runner.py` — 完全重写

这是核心任务。将 runner.py 重写为精简的编排逻辑，使用 strategies 和新模块。

- [ ] **Step 1: 重写 `runner.py`**

```python
"""VehicleMemBench 评估基准的测试运行器（编排层）."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from . import BenchMemoryMode
from .loader import load_history_cache, load_prep_cache, load_qa_safe
from .paths import ensure_output_dir, file_output_dir, prep_path
from .reporter import report  # noqa: F401 — 重导出
from .strategies import STRATEGIES, MemoryStrategy, VehicleMemBenchError

if TYPE_CHECKING:
    from evaluation.agent_client import AgentClient

logger = logging.getLogger(__name__)

# 重导出路径工具，保持公共 API 不变
from .paths import (  # noqa: F401
    BENCHMARK_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    VENDOR_DIR,
    file_output_dir,
    prep_path,
    query_result_path,
    setup_vehiclemembench_path,
)

try:
    _QUERY_CONCURRENCY_LIMIT = int(os.environ.get("BENCHMARK_QUERY_CONCURRENCY", "4"))
except ValueError:
    _QUERY_CONCURRENCY_LIMIT = 4

from .model_config import get_benchmark_config


@lru_cache(maxsize=1)
def _get_agent_client() -> AgentClient:
    cfg = get_benchmark_config()
    from evaluation.agent_client import AgentClient

    return AgentClient(
        api_base=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )


def _parse_memory_types(memory_types: str) -> list[BenchMemoryMode]:
    types = [t.strip() for t in memory_types.split(",") if t.strip()]
    supported = frozenset(STRATEGIES.keys())
    invalid = [t for t in types if t not in supported]
    if invalid:
        msg = f"Unsupported memory_types: {invalid}. Supported: {sorted(supported)}"
        raise ValueError(msg)
    return [BenchMemoryMode(t) for t in types]


def parse_file_range(range_str: str) -> list[int]:
    """将形如 '1-5' 或 '1,3,5' 的文件范围字符串解析为整数列表."""
    result = []
    for raw_part in range_str.split(","):
        part = raw_part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            result.extend(range(min(a, b), max(a, b) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def _resolve_agent_client(strategies_list: list[MemoryStrategy]) -> AgentClient | None:
    """按需解析 agent client."""
    if any(s.needs_agent_for_prep() for s in strategies_list):
        try:
            return _get_agent_client()
        except Exception as e:
            msg = "agent_client not initialized but required by memory types"
            raise VehicleMemBenchError(msg) from e
    return None


async def _prepare_one_type(
    fnum: int,
    mtype: BenchMemoryMode,
    history_cache: dict[int, str],
    semaphore: asyncio.Semaphore,
    agent_client: AgentClient | None,
) -> None:
    """为单个文件+记忆类型准备数据."""
    strategy = STRATEGIES[mtype]
    fdir = file_output_dir(mtype, fnum)

    if mtype in {BenchMemoryMode.NONE, BenchMemoryMode.GOLD}:
        if fdir.exists():
            logger.info("[skip] %s file %d already prepared", mtype, fnum)
            return
        fdir.mkdir(parents=True, exist_ok=True)
        logger.info("[prepare] %s file %d...", mtype, fnum)
        return

    pp = prep_path(mtype, fnum)
    if pp.exists():
        logger.info("[skip] %s file %d already prepared", mtype, fnum)
        return

    logger.info("[prepare] %s file %d...", mtype, fnum)
    try:
        history_text = history_cache.get(fnum, "")
        result = await strategy.prepare(
            history_text, fdir, agent_client, semaphore,
        )
        if result is not None:
            fdir.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(pp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception:
        logger.exception("[error] %s file %d", mtype, fnum)
        raise


async def prepare(
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
) -> None:
    """为指定文件范围和记忆类型准备基准测试数据."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    strategies_list = [STRATEGIES[t] for t in types]
    ensure_output_dir()
    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    agent_client = _resolve_agent_client(strategies_list)
    history_cache = await load_history_cache(file_nums, strategies_list)

    prep_results = await asyncio.gather(
        *(
            _prepare_one_type(fnum, mtype, history_cache, semaphore, agent_client)
            for fnum in file_nums
            for mtype in types
        ),
        return_exceptions=True,
    )
    failed = sum(1 for r in prep_results if isinstance(r, BaseException))
    if failed:
        logger.info("[prepare] done with %d failures", failed)


async def _run_single(
    evaluator,
    events: list[dict],
    memory_type: BenchMemoryMode,
    file_num: int,
) -> None:
    """运行单个文件的查询评估."""

    async def _eval_and_save(idx: int, event: dict) -> None:
        from .paths import query_result_path

        qp = query_result_path(memory_type, file_num, idx)
        try:
            async with aiofiles.open(qp, encoding="utf-8") as f:
                existing = json.loads(await f.read())
            if isinstance(existing, dict) and not existing.get("failed"):
                return
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            pass

        try:
            query = event.get("query", "")
            reasoning_type = event.get("reasoning_type", "")
            ref_calls_from_event = event.get("new_answer", [])
            from evaluation.model_evaluation import parse_answer_to_tools

            ref_calls = parse_answer_to_tools(ref_calls_from_event)
            gold_memory = event.get("gold_memory", "")
            task: dict = {
                "query": query,
                "tools": ref_calls,
                "reasoning_type": reasoning_type,
            }
            result = await evaluator.evaluate(task, idx, gold_memory)
            if result is not None:
                result["source_file"] = file_num
                result["event_index"] = idx
                result["memory_type"] = memory_type
                async with aiofiles.open(qp, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.exception("  [error] query %d", idx)
            fail_record = {
                "failed": True,
                "error": str(e),
                "source_file": file_num,
                "event_index": idx,
                "memory_type": memory_type,
            }
            try:
                async with aiofiles.open(qp, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(fail_record, ensure_ascii=False, indent=2))
            except OSError:
                logger.exception(
                    "  [error] failed to write error record for query %d",
                    idx,
                )

    gather_results = await asyncio.gather(
        *(_eval_and_save(i, e) for i, e in enumerate(events)),
        return_exceptions=True,
    )
    silent_failures = [r for r in gather_results if isinstance(r, BaseException)]
    if silent_failures:
        logger.warning("  [warn] %d queries failed silently", len(silent_failures))


async def _run_one_type(
    fnum: int,
    mtype: BenchMemoryMode,
    qa_cache: dict[int, dict | None],
    prep_cache: dict[tuple[BenchMemoryMode, int], dict | None],
    agent_client: AgentClient,
    reflect_num: int,
    query_semaphore: asyncio.Semaphore,
) -> None:
    """为单个文件+记忆类型运行评估."""
    prep_data = prep_cache.get((mtype, fnum))
    if prep_data is None:
        logger.info("[skip] %s file %d not prepared", mtype, fnum)
        return

    qa_data = qa_cache.get(fnum)
    if qa_data is None:
        logger.info("[skip] %s file %d qa data not found", mtype, fnum)
        return

    events = qa_data.get("related_to_vehicle_preference", [])
    if not events:
        return

    fdir = file_output_dir(mtype, fnum)
    fdir.mkdir(parents=True, exist_ok=True)

    logger.info("[run] %s file %d: %d queries...", mtype, fnum, len(events))

    strategy = STRATEGIES[mtype]
    evaluator = await strategy.create_evaluator(
        agent_client, prep_data, fnum, reflect_num, query_semaphore,
    )
    await _run_single(evaluator, events, mtype, fnum)


async def run(
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
    reflect_num: int = 10,
) -> None:
    """为指定文件范围和记忆类型运行基准评估."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    ensure_output_dir()

    qa_pairs = await asyncio.gather(*(load_qa_safe(f) for f in file_nums))
    qa_cache = dict(qa_pairs)
    prep_cache = await load_prep_cache(file_nums, types)

    query_semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    run_results = await asyncio.gather(
        *(
            _run_one_type(
                fnum, mtype, qa_cache, prep_cache,
                agent_client, reflect_num, query_semaphore,
            )
            for fnum in file_nums
            for mtype in types
        ),
        return_exceptions=True,
    )
    failed = sum(1 for r in run_results if isinstance(r, BaseException))
    if failed:
        logger.info("[run] done with %d file-level failures", failed)
```

- [ ] **Step 2: 运行测试，确认基本导入无误**

运行：`uv run python -c "from vendor_adapter.VehicleMemBench.runner import prepare, run, report"`
预期：无 ImportError

- [ ] **Step 3: 提交**

```bash
git add vendor_adapter/VehicleMemBench/runner.py
git commit -m "refactor: rewrite runner.py as slim orchestration layer"
```

---

### Task 11: 更新测试

**Files:**
- Modify: `tests/test_vendor_adapter/test_runner.py`
- Modify: `tests/test_vendor_adapter/test_common.py`（已在 Task 4 完成）

- [ ] **Step 1: 更新 `test_runner.py` 的 import 和 monkeypatch 路径**

将所有 monkeypatch 路径按以下映射更新：

| 旧路径 | 新路径 |
|-------|--------|
| `vendor_adapter.VehicleMemBench.runner.OUTPUT_DIR` | `vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR` |
| `vendor_adapter.VehicleMemBench.runner._load_qa` | `vendor_adapter.VehicleMemBench.loader.load_qa` |
| `vendor_adapter.VehicleMemBench.runner._evaluate_query` | `vendor_adapter.VehicleMemBench.runner._evaluate_query`（已移除，需重写测试） |
| `vendor_adapter.VehicleMemBench.runner._get_agent_client` | `vendor_adapter.VehicleMemBench.runner._get_agent_client`（不变） |
| `vendor_adapter.VehicleMemBench.runner.get_benchmark_config` | `vendor_adapter.VehicleMemBench.reporter.get_benchmark_config` |

`test_run_skips_existing_query_files` 测试需要重写：mock strategy 的 `create_evaluator` 而非 `_evaluate_query`。

- [ ] **Step 2: 运行测试**

运行：`uv run pytest tests/test_vendor_adapter/ -v`
预期：全部通过

- [ ] **Step 3: 提交**

```bash
git add tests/test_vendor_adapter/test_runner.py
git commit -m "test: update test_runner monkeypatch paths for new module layout"
```

---

### Task 12: 删除旧的 `memory_adapters/` 目录

**Files:**
- Delete: `vendor_adapter/VehicleMemBench/memory_adapters/__init__.py`
- Delete: `vendor_adapter/VehicleMemBench/memory_adapters/common.py`
- Delete: `vendor_adapter/VehicleMemBench/memory_adapters/memory_bank_adapter.py`

- [ ] **Step 1: 确认无外部引用指向旧路径**

搜索项目中所有 `from vendor_adapter.VehicleMemBench.memory_adapters` 和 `import vendor_adapter.VehicleMemBench.memory_adapters` 引用。

- [ ] **Step 2: 删除旧文件**

```bash
rm -rf vendor_adapter/VehicleMemBench/memory_adapters/
```

- [ ] **Step 3: 运行测试**

运行：`uv run pytest tests/test_vendor_adapter/ -v`
预期：全部通过

- [ ] **Step 4: 提交**

```bash
git add -A vendor_adapter/VehicleMemBench/memory_adapters/
git commit -m "refactor: remove old memory_adapters directory"
```

---

### Task 13: 新增 `test_strategies.py`

**Files:**
- Create: `tests/test_vendor_adapter/test_strategies.py`

- [ ] **Step 1: 创建策略测试**

```python
"""策略模块测试."""

import pytest

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.strategies import STRATEGIES


def test_strategies_registry_has_all_modes() -> None:
    """测试注册表包含所有记忆模式."""
    assert set(STRATEGIES.keys()) == set(BenchMemoryMode)


@pytest.mark.parametrize(
    "mode,expected_needs_history,expected_needs_agent",
    [
        (BenchMemoryMode.NONE, False, False),
        (BenchMemoryMode.GOLD, False, False),
        (BenchMemoryMode.KV, True, True),
        (BenchMemoryMode.MEMORY_BANK, True, False),
    ],
)
def test_strategy_properties(
    mode: BenchMemoryMode,
    expected_needs_history: bool,
    expected_needs_agent: bool,
) -> None:
    """测试每个策略的属性."""
    strategy = STRATEGIES[mode]
    assert strategy.mode == mode
    assert strategy.needs_history() == expected_needs_history
    assert strategy.needs_agent_for_prep() == expected_needs_agent
```

- [ ] **Step 2: 运行测试**

运行：`uv run pytest tests/test_vendor_adapter/test_strategies.py -v`
预期：全部通过

- [ ] **Step 3: 提交**

```bash
git add tests/test_vendor_adapter/test_strategies.py
git commit -m "test: add strategy registry and property tests"
```

---

### Task 14: 完整验证

- [ ] **Step 1: 运行 ruff check**

运行：`uv run ruff check --fix`
预期：无错误

- [ ] **Step 2: 运行 ruff format**

运行：`uv run ruff format`
预期：格式化完成

- [ ] **Step 3: 运行 ty 类型检查**

运行：`uv run ty check`
预期：无类型错误

- [ ] **Step 4: 运行完整测试**

运行：`uv run pytest tests/test_vendor_adapter/ -v`
预期：全部通过

- [ ] **Step 5: 最终提交（如有 lint 修复）**

```bash
git add -A && git commit -m "style: fix lint and format issues"
```
