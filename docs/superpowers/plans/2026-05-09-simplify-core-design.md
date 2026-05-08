# 核心模块简化实现计划

> **面向执行者：** 推荐使用 `superpowers:executing-plans` 逐任务执行。步骤用复选框（`- [ ]`）跟踪进度。

**目标：** 消除重复代码、职责不清、跨模块私有函数引用——5 项变更（P0~P4）

**架构：** 拆分大文件为单一职责模块 → 消除样板代码 → 扁平化嵌套 → 用 strawberry pydantic 自动生成 Output 类型 → 清理路径重复

**技术栈：** Python 3.14, Strawberry GraphQL 0.312.2, Pydantic 2.12.5

---

## 文件结构

```
新建: api/resolvers/errors.py      # GraphQL 异常类
新建: api/resolvers/converters.py  # 类型转换 + preset 存取
修改: api/resolvers/mutation.py    # 瘦身，移除异常类和转换函数
修改: api/resolvers/query.py       # 改导入路径
修改: api/resolvers/__init__.py    # 导出新模块（仅注释）
修改: models/settings.py           # 提取 _make_provider_config 工厂
修改: agents/workflow.py           # 提取 _safe_memory_search/_safe_memory_history
修改: api/graphql_schema.py        # P3: Output 类型用 pydantic 自动生成
修改: storage/init_data.py         # 删除 get_data_dir，导入 config.DATA_DIR
```

独立变更（可并行）：P1, P2, P4。P0→P3 顺序依赖（P3 需 P0 的 converters.py）。

---

### 任务 1：P0 — 拆分 mutation.py（第一阶段：新建 errors.py）

**文件：**
- 创建：`app/api/resolvers/errors.py`

- [ ] **步骤 1：创建 errors.py，迁移 GraphQL 异常类**

```python
"""GraphQL 异常类."""

from graphql.error import GraphQLError


class InternalServerError(GraphQLError):
    """内部服务器错误."""

    def __init__(self) -> None:
        super().__init__("Internal server error")


class GraphQLInvalidActionError(GraphQLError):
    """无效的操作类型."""

    def __init__(self, action: str) -> None:
        super().__init__(f"Invalid action: {action!r}")


class GraphQLEventNotFoundError(GraphQLError):
    """事件不存在."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event not found: {event_id!r}")
```

- [ ] **步骤 2：更新 mutation.py，从 errors 导入异常类**

从 `mutation.py` 中删除 `InternalServerError`、`GraphQLInvalidActionError`、`GraphQLEventNotFoundError` 三个类定义（L44-65），改为：

```python
from app.api.resolvers.errors import (
    GraphQLEventNotFoundError,
    GraphQLInvalidActionError,
    InternalServerError,
)
```

- [ ] **步骤 3：验证——运行现有 GraphQL 测试**

```bash
uv run pytest tests/test_graphql.py -v --timeout=60
```

期望：全部通过（异常类仅移动位置，行为不变）

- [ ] **步骤 4：Commit**

```bash
git add app/api/resolvers/errors.py app/api/resolvers/mutation.py
git commit -m "refactor: 提取 GraphQL 异常类到 api/resolvers/errors.py"
```

---

### 任务 2：P0 — 拆分 mutation.py（第二阶段：新建 converters.py）

**文件：**
- 创建：`app/api/resolvers/converters.py`
- 修改：`app/api/resolvers/mutation.py`（移除转换函数）
- 修改：`app/api/resolvers/query.py`（改导入）

- [ ] **步骤 1：创建 converters.py，迁移类型转换函数和 preset 存取函数**

将以下函数从 `mutation.py` 移至 `converters.py`（L106-192），去掉 `_` 前缀改为公开：

```python
"""Strawberry ↔ Pydantic 类型转换工具."""

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any, cast

from app.api.graphql_schema import (
    DriverStateGQL,
    DrivingContextGQL,
    DrivingContextInput,
    GeoLocationGQL,
    ScenarioPresetGQL,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
)
from app.config import DATA_DIR
from app.schemas.context import DrivingContext, ScenarioPreset
from app.storage.toml_store import TOMLStore


def strawberry_to_plain(obj: object) -> object:
    """递归将 Strawberry 类型转普通 Python 对象（Enum→.value，dataclass→dict）。

    跳过 None 值字段，避免 Pydantic 对非 Optional 字段收到 None 引发验证错误。
    """
    if obj is None or isinstance(obj, (str, bytes, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [strawberry_to_plain(item) for item in obj]
    if dataclasses.is_dataclass(obj):
        return {
            f.name: strawberry_to_plain(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if getattr(obj, f.name) is not None
        }
    return obj


def input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    """将 Strawberry GraphQL input 转为 Pydantic DrivingContext。"""
    data = cast("dict[str, Any]", strawberry_to_plain(input_obj))
    return DrivingContext.model_validate(
        {k: v for k, v in data.items() if v is not None},
    )


def dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    """将 dict 转为 DrivingContextGQL（通过 Pydantic 验证后手工构造）。

    注意：P3 实施后此函数被 DrivingContextGQL.from_pydantic() 替代。
    """
    ctx = DrivingContext.model_validate(d)
    dest = ctx.spatial.destination
    return DrivingContextGQL(
        driver=DriverStateGQL(
            emotion=ctx.driver.emotion,
            workload=ctx.driver.workload,
            fatigue_level=ctx.driver.fatigue_level,
        ),
        spatial=SpatioTemporalContextGQL(
            current_location=GeoLocationGQL(
                latitude=ctx.spatial.current_location.latitude,
                longitude=ctx.spatial.current_location.longitude,
                address=ctx.spatial.current_location.address,
                speed_kmh=ctx.spatial.current_location.speed_kmh,
            ),
            destination=GeoLocationGQL(
                latitude=dest.latitude,
                longitude=dest.longitude,
                address=dest.address,
                speed_kmh=dest.speed_kmh,
            )
            if dest is not None
            else None,
            eta_minutes=ctx.spatial.eta_minutes,
            heading=ctx.spatial.heading,
        ),
        traffic=TrafficConditionGQL(
            congestion_level=ctx.traffic.congestion_level,
            incidents=ctx.traffic.incidents,
            estimated_delay_minutes=ctx.traffic.estimated_delay_minutes,
        ),
        scenario=ctx.scenario,
    )


def preset_store() -> TOMLStore:
    """获取场景预设存储实例。"""
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    """将 dict 转为 ScenarioPresetGQL。"""
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )
```

- [ ] **步骤 2：修改 mutation.py，从 converters 导入**

删除 mutation.py 中的 `_strawberry_to_plain`、`_input_to_context`、`_dict_to_gql_context`、`_preset_store`、`_to_gql_preset` 函数定义（L106-192）。

添加导入：

```python
from app.api.resolvers.converters import (
    input_to_context,
    preset_store,
    to_gql_preset,
)
```

修改函数内调用：
- `_preset_store()` → `preset_store()`
- `_input_to_context(...)` → `input_to_context(...)`

- [ ] **步骤 3：修改 query.py，从 converters 导入**

```python
# 旧导入（删除）
from app.api.resolvers.mutation import _preset_store, _to_gql_preset

# 新导入
from app.api.resolvers.converters import preset_store, to_gql_preset
```

函数内调用：
- `_preset_store()` → `preset_store()`
- `_to_gql_preset(p)` → `to_gql_preset(p)`

- [ ] **步骤 4：验证**

```bash
uv run ruff check --fix app/api/resolvers/
uv run ruff format app/api/resolvers/
uv run ty check app/api/resolvers/
uv run pytest tests/test_graphql.py -v --timeout=60
```

期望：全部通过

- [ ] **步骤 5：Commit**

```bash
git add app/api/resolvers/converters.py app/api/resolvers/mutation.py app/api/resolvers/query.py
git commit -m "refactor: 提取类型转换函数到 api/resolvers/converters.py，消除 query→mutation 私有导入"
```

---

### 任务 3：P1 — 消除 settings.py from_dict 样板

**文件：**
- 修改：`app/models/settings.py`

- [ ] **步骤 1：添加 _make_provider_config 工厂函数，修改三个 from_dict**

在 `settings.py` 的 `_build_provider_config_from_dict` 函数之后添加：

```python
from typing import TypeVar

_T = TypeVar("_T")


def _make_provider_config(
    cls: type[_T],
    d: dict[str, Any],
    defaults: dict[str, Any],
) -> _T:
    """泛型工厂：从字典构建 ProviderConfig 子类实例。"""
    provider, extra = _build_provider_config_from_dict(d, defaults)
    return cls(provider=provider, **extra)
```

修改三个类的 `from_dict`：

```python
# LLMProviderConfig.from_dict（L55-62）
@classmethod
def from_dict(cls, d: dict[str, Any]) -> LLMProviderConfig:
    return _make_provider_config(cls, d, {"temperature": 0.7, "concurrency": 4})

# EmbeddingProviderConfig.from_dict（L71-75）
@classmethod
def from_dict(cls, d: dict[str, Any]) -> EmbeddingProviderConfig:
    return _make_provider_config(cls, d, {})

# JudgeProviderConfig.from_dict（L86-89）
@classmethod
def from_dict(cls, d: dict[str, Any]) -> JudgeProviderConfig:
    return _make_provider_config(cls, d, {"temperature": 0.1})
```

- [ ] **步骤 2：验证**

```bash
uv run ruff check --fix app/models/settings.py
uv run ruff format app/models/settings.py
uv run ty check app/models/settings.py
uv run pytest tests/test_settings.py -v --timeout=60
```

期望：全部通过（from_dict 行为不变）

- [ ] **步骤 3：Commit**

```bash
git add app/models/settings.py
git commit -m "refactor: 提取 _make_provider_config 工厂消除 from_dict 样板"
```

---

### 任务 4：P2 — 扁平化 workflow.py _search_memories

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：在 AgentWorkflow 类中添加 _safe_memory_search 和 _safe_memory_history**

在 `_search_memories` 方法之前插入两个新方法：

```python
async def _safe_memory_search(self, user_input: str) -> list[dict] | None:
    """搜索相关记忆，失败或结果为空返回 None。"""
    try:
        events = await self.memory_module.search(
            user_input,
            mode=self._memory_mode,
        )
        if events:
            return [e.to_public() for e in events]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
        logger.warning("Memory search failed: %s", e)
    return None


async def _safe_memory_history(self) -> list[dict]:
    """获取最近历史记录，失败返回空列表。"""
    try:
        history = await self.memory_module.get_history(mode=self._memory_mode)
        return [e.model_dump() for e in history]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
        logger.warning("Memory get_history failed: %s", e)
        return []
```

- [ ] **步骤 2：替换 _search_memories 方法体**

```python
async def _search_memories(
    self,
    user_input: str,
) -> list[dict]:
    """搜索相关记忆，失败时回退到最近历史记录。"""
    if not user_input:
        return await self._safe_memory_history()
    events = await self._safe_memory_search(user_input)
    if events:
        return events
    return await self._safe_memory_history()
```

- [ ] **步骤 3：验证**

```bash
uv run ruff check --fix app/agents/workflow.py
uv run ruff format app/agents/workflow.py
uv run ty check app/agents/workflow.py
```

期望：无新增 lint/type 错误（workflow.py 通过 memory 调用测试需完整服务，lint/type 检查即可）

- [ ] **步骤 4：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: 扁平化 _search_memories，提取 safe_search/safe_history"
```

---

### 任务 5：P3 — Output 类型自动生成（strawberry pydantic）

**文件：**
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/converters.py`

- [ ] **步骤 1：在 graphql_schema.py 中用 pydantic 自动生成替换手动 Output 类型**

删除 `graphql_schema.py` 中的 5 个手动 `@strawberry.type` 类（L139-185）：
- `GeoLocationGQL`
- `DriverStateGQL`
- `SpatioTemporalContextGQL`
- `TrafficConditionGQL`
- `DrivingContextGQL`

替换为：

```python
from strawberry.experimental.pydantic import type as pydantic_type
from strawberry import auto

from app.schemas.context import (
    DriverState as _DriverState,
    GeoLocation as _GeoLocation,
    SpatioTemporalContext as _SpatioTemporalContext,
    TrafficCondition as _TrafficCondition,
    DrivingContext as _DrivingContext,
)


@pydantic_type(_GeoLocation)
class GeoLocationGQL:
    latitude: auto
    longitude: auto
    address: auto
    speed_kmh: auto


@pydantic_type(_DriverState)
class DriverStateGQL:
    emotion: auto
    workload: auto
    fatigue_level: auto


@pydantic_type(_TrafficCondition)
class TrafficConditionGQL:
    congestion_level: auto
    incidents: auto
    estimated_delay_minutes: auto


@pydantic_type(_SpatioTemporalContext)
class SpatioTemporalContextGQL:
    current_location: auto
    destination: auto
    eta_minutes: auto
    heading: auto


@pydantic_type(_DrivingContext)
class DrivingContextGQL:
    driver: auto
    spatial: auto
    traffic: auto
    scenario: auto
```

- [ ] **步骤 2：简化 converters.py 中的 dict_to_gql_context**

替换 `dict_to_gql_context` 函数体：

```python
def dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    """将 dict 转为 DrivingContextGQL（通过 Pydantic→from_pydantic）。"""
    ctx = DrivingContext.model_validate(d)
    return DrivingContextGQL.from_pydantic(ctx)
```

- [ ] **步骤 3：验证**

```bash
uv run ruff check --fix app/api/graphql_schema.py app/api/resolvers/converters.py
uv run ruff format app/api/graphql_schema.py app/api/resolvers/converters.py
uv run ty check app/api/graphql_schema.py app/api/resolvers/converters.py
uv run pytest tests/test_graphql.py -v --timeout=60
uv run pytest tests/test_context_schemas.py -v --timeout=60
```

期望：全部通过。Output 类型通过 `from_pydantic()` 生成，字段名和类型一致。

- [ ] **步骤 4：Commit**

```bash
git add app/api/graphql_schema.py app/api/resolvers/converters.py
git commit -m "refactor: 用 strawberry pydantic 自动生成 Output 类型，简化为 from_pydantic"
```

---

### 任务 6：P4 — 清理 init_data.py 路径重复

**文件：**
- 修改：`app/storage/init_data.py`

- [ ] **步骤 1：替换 get_data_dir，直接用 config.DATA_DIR**

删除 `get_data_dir` 函数（L8-10），修改 `init_storage`：

```python
"""数据目录初始化与默认数据填充."""

from pathlib import Path

import tomli_w

from app.config import DATA_DIR


def init_storage(data_dir: Path | None = None) -> None:
    """初始化存储目录和数据文件。"""
    if data_dir is None:
        data_dir = DATA_DIR
    # ... 其余不变
```

同步修改 `if __name__ == "__main__"` 块（L57-58）：

```python
if __name__ == "__main__":
    init_storage()
```

- [ ] **步骤 2：验证**

```bash
uv run ruff check --fix app/storage/init_data.py
uv run ruff format app/storage/init_data.py
uv run ty check app/storage/init_data.py
uv run python -c "from app.storage.init_data import init_storage; init_storage()"
```

期望：`init_storage()` 正常执行，无异常

- [ ] **步骤 3：Commit**

```bash
git add app/storage/init_data.py
git commit -m "refactor: 删除 init_data.py get_data_dir，复用 config.DATA_DIR"
```

---

### 任务 7：最终验证

- [ ] **步骤 1：全量 lint + type check**

```bash
uv run ruff check --fix
uv run ruff format
uv run ty check
```

期望：无错误

- [ ] **步骤 2：全量测试**

```bash
uv run pytest tests/ -v --timeout=60 -k "not (test_llm or test_embedding or test_memory_bank)"
```

排除需要真实 LLM/Embedding 的测试。期望：全部通过。

- [ ] **步骤 3：最终 Commit（如有残留变更）**

---

## 依赖图

```
任务1 (P0-errors) ──┐
                     ├──► 任务2 (P0-converters) ──► 任务5 (P3)
任务3 (P1) ─────────┤
任务4 (P2) ─────────┤
任务6 (P4) ─────────┘
                     └──► 任务7 (最终验证)
```

任务 1-2 必须顺序执行（文件拆分）。任务 3、4、6 可并行。任务 5 依赖任务 2（需要 converters.py 存在）。
