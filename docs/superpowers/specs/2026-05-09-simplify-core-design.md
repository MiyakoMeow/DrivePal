# 核心模块简化与精确化设计

日期：2026-05-09
范围：app/ 排除 app/memory/
版本：strawberry-graphql 0.312.2, Pydantic 2.12.5

## 目标

消除重复代码、职责不清、跨模块私有函数引用，提升代码精确性和可维护性。

## 变更概览

| 优先级 | 变更项 | 文件影响 |
|--------|--------|----------|
| P0 | 拆分 mutation.py | api/resolvers/ 3文件 |
| P1 | 消除 settings.py from_dict 样板 | models/settings.py |
| P2 | 扁平化 _search_memories | agents/workflow.py |
| P3 | Output 类型自动生成（Pydantic→Strawberry） | api/graphql_schema.py, api/resolvers/converters.py |
| P4 | 清理 init_data.py 重复 | storage/init_data.py |

---

## P0：拆分 mutation.py

### 现状

`api/resolvers/mutation.py`（296行）包含：
- Mutation resolver 类 (4 方法)
- 3 个 GraphQL 异常类
- 5 个类型转换工具函数
- 1 个异常包装器 `_safe_memory_call`
- query.py 导入 mutation.py 的 `_preset_store`、`_to_gql_preset`（私有函数跨模块使用）

### 设计

拆为 3 个文件：

```
api/resolvers/
├── errors.py        # GraphQL 异常类（3 个异常，~40 行）
├── converters.py    # 类型转换工具（_strawberry_to_plain, _input_to_context, _dict_to_gql_context, _preset_store, _to_gql_preset, ~90 行）
└── mutation.py      # Mutation resolver 类 + _safe_memory_call（~170 行）
```

**规则**：
1. `converters.py` 中函数全部公开（去掉 `_` 前缀），供 `mutation.py` 和 `query.py` 使用
2. `errors.py` 异常类供 `mutation.py` 使用
3. `query.py` 改为 `from app.api.resolvers.converters import preset_store, to_gql_preset`

### 与 P3 的协同

P3 实施后 `_dict_to_gql_context` 从 63 行手工字段组装简化为 2 行 (`DrivingContextGQL.from_pydantic(ctx)`)。`converters.py` 中不再需要此函数，可删除。

**实施顺序**：P0 创建 `converters.py`（含 `_dict_to_gql_context`），P3 在同一 PR 的第二阶段删除之。分两阶段提交避免"新建即删"的浪费。

---

## P1：消除 settings.py from_dict 样板

### 现状

`LLMProviderConfig`、`EmbeddingProviderConfig`、`JudgeProviderConfig` 三个类各自实现 `from_dict`：

```python
@classmethod
def from_dict(cls, d: dict) -> LLMProviderConfig:
    provider, extra = _build_provider_config_from_dict(d, {"temperature": 0.7, "concurrency": 4})
    return cls(provider=provider, **extra)
```

三个方法结构完全相同，仅默认值不同（~30 行样板）。

### 设计（推荐方案）

不合并类，仅提取 `from_dict` 为独立泛型工厂函数，放在 `app/models/settings.py` 中：

```python
from typing import TypeVar

T = TypeVar("T")

def _make_provider_config(cls: type[T], d: dict, defaults: dict[str, Any]) -> T:
    provider, extra = _build_provider_config_from_dict(d, defaults)
    return cls(provider=provider, **extra)
```

三个 `from_dict` 各变为一行委托，样板从 30 行减至 6 行。类结构不变——现有 `provider.temperature` 等访问点无需修改。风险最低。

### 备选方案（不推荐）

三个 Config 类合并为一个通用 `ProviderConfig`，用 `extra` dict 存储温度等字段。缺点：`provider.temperature` 改为 `provider.extra["temperature"]`，需同步修改所有访问点，收益不抵变动成本。

---

## P2：扁平化 _search_memories

### 现状

`workflow.py` 中 3 层 try/except 嵌套实现 fallback 链：

```
search → except → get_history → except → []
```

### 设计

提取两个辅助方法：

```python
async def _safe_memory_search(self, user_input: str) -> list[dict] | None:
    """搜索记忆，失败返回 None."""
    try:
        events = await self.memory_module.search(user_input, mode=self._memory_mode)
        if events:
            return [e.to_public() for e in events]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        pass
    return None

async def _safe_memory_history(self) -> list[dict]:
    """获取历史，失败返回空列表."""
    try:
        history = await self.memory_module.get_history(mode=self._memory_mode)
        return [e.model_dump() for e in history]
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return []
```

主函数变为平铺：

```python
async def _search_memories(self, user_input: str) -> list[dict]:
    if not user_input:
        return await self._safe_memory_history()
    events = await self._safe_memory_search(user_input)
    if events:
        return events
    return await self._safe_memory_history()
```

重试逻辑不变（search → history fallback），但代码扁平化。

---

## P3：Pydantic↔Strawberry 类型合并（Output 方向）

### 验证结论

已通过 10 项测试验证 `strawberry.experimental.pydantic`（0.312.2）与项目 Pydantic 模型的兼容性：

| 测试项 | 结果 | 说明 |
|--------|------|------|
| Output 类型生成 | ✅ 通过 | `@pydantic_type(Model)` + `strawberry.auto` 注解生成正确的 GraphQL 输出类型 |
| Literal→Enum 输出 | ✅ 通过 | `from_pydantic()` 正确将 Pydantic Literal 转为 str 值 |
| 嵌套 Optional | ✅ 通过 | `GeoLocation \| None` → `GeoLocationGQL \| None` |
| list[str] | ✅ 通过 | `TrafficCondition.incidents` 正确映射为 `list[str]` |
| 往返转换 | ✅ 通过 | Input(manual) → Pydantic → Output(auto) 链路正常 |
| Optional=None | ✅ 通过 | `destination=None` 在 output 中正确为 `None` |
| **Input 类型 to_pydantic** | ❌ 失败 | Pydantic `Literal` 字段在 strawberry pydantic 中不自动创建 Enum 映射；`to_pydantic()` 传入的 StrawberryEnum 对象被 Pydantic 拒绝（检验 `Literal` 而非 `Enum`） |
| **Input 替代方案** | ❌ 不可行 | 将 Pydantic `Literal` 改为 Python `Enum` 会导致 `model_dump()` 输出枚举对象而非字符串，破坏 rules.py 的字符串比较（`ctx.get("scenario") == "highway"`）。使用 `model_dump(mode='json')` 需全局修改 |

### 结论与设计

**Input 方向不可行，Output 方向完全可行。** 采取最优方案：

- **Input 类型**：保持手动 Strawberry 定义（`graphql_schema.py` 中 5 个 `@strawberry.input` 类不变）
- **Output 类型**：用 `strawberry.experimental.pydantic` 自动生成，替代手动定义的 5 个 `@strawberry.type` 类
- **转换函数**：
  - `_strawberry_to_plain` / `_input_to_context`：**保留**（Input 方向不变）
  - `_dict_to_gql_context` 63 行手工字段组装：**删除**，替换为：

```python
ctx = DrivingContext.model_validate(d)
return DrivingContextGQL.from_pydantic(ctx)
```

### 具体变更

`api/graphql_schema.py` 中 **删除** (~120 行)：
- `GeoLocationGQL`（手动 8 行）
- `DriverStateGQL`（手动 5 行）
- `SpatioTemporalContextGQL`（手动 7 行）
- `TrafficConditionGQL`（手动 7 行）
- `DrivingContextGQL`（手动 10 行）

**替换为** (~30 行)：
```python
from strawberry.experimental.pydantic import type as pydantic_type
from strawberry import auto
from app.schemas.context import (
    DriverState, GeoLocation, SpatioTemporalContext, TrafficCondition, DrivingContext,
)

@pydantic_type(GeoLocation)
class GeoLocationGQL:
    latitude: auto; longitude: auto; address: auto; speed_kmh: auto

@pydantic_type(DriverState)
class DriverStateGQL:
    emotion: auto; workload: auto; fatigue_level: auto

@pydantic_type(TrafficCondition)
class TrafficConditionGQL:
    congestion_level: auto; incidents: auto; estimated_delay_minutes: auto

@pydantic_type(SpatioTemporalContext)
class SpatioTemporalContextGQL:
    current_location: auto; destination: auto; eta_minutes: auto; heading: auto

@pydantic_type(DrivingContext)
class DrivingContextGQL:
    driver: auto; spatial: auto; traffic: auto; scenario: auto
```

### 净收益

- `graphql_schema.py`：~231 行 → ~141 行（-90 行）
- `_dict_to_gql_context` 函数：63 行 → 2 行（-61 行）

**总计：~150 行消除，无破坏性变更。** 所有 Input 类型和转换逻辑保持不变，仅 Output 方向简化。

### 实施策略

无需分步验证——Output 方向已验证通过。直接实施。

---

## P4：清理 init_data.py 重复

### 现状

`init_data.py` 中 `get_data_dir()` 用 `__file__` 计算路径，与 `config.py` 中 `DATA_DIR`（环境变量优先）逻辑重复。`init_storage(data_dir)` 已接受参数，但默认值调 `get_data_dir()`。

### 设计

删除 `get_data_dir()`，改为模块级导入 `config.DATA_DIR`（已验证无循环依赖）：

```python
from app.config import DATA_DIR

def init_storage(data_dir: Path | None = None) -> None:
    if data_dir is None:
        data_dir = DATA_DIR
```

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| **新建** | `app/api/resolvers/errors.py` |
| **新建** | `app/api/resolvers/converters.py` |
| **修改** | `app/api/resolvers/mutation.py`（瘦身） |
| **修改** | `app/api/resolvers/query.py`（改导入路径） |
| **修改** | `app/api/resolvers/__init__.py`（导出新模块） |
| **修改** | `app/models/settings.py`（消除 from_dict 样板） |
| **修改** | `app/agents/workflow.py`（扁平化 _search_memories） |
| **修改** | `app/api/graphql_schema.py`（P3: Output 类型用 pydantic 自动生成，Input 类型保持手动） |
| **修改** | `app/api/resolvers/converters.py`（P3: 删除 `_dict_to_gql_context`，用 `from_pydantic` 替代） |
| **修改** | `app/api/main.py`（无变更，依赖通过 resolvers/ 模块路由不变） |
| **修改** | `app/storage/init_data.py`（删除 get_data_dir） |

**不变文件**：
- `app/config.py`（保持）
- `app/schemas/context.py`（Pydantic 模型不变）
- `app/models/chat.py`（保持）
- `app/models/embedding.py`（保持）
- `app/models/types.py`（保持）

---

## 测试影响

- `tests/test_graphql.py`：验证 processQuery 正确性——P3 后 Output 类型通过 `from_pydantic()` 生成，字段名和类型一致，现有测试应通过
- `tests/test_context_schemas.py`：不变（Pydantic 模型未改）
- `tests/test_settings.py`：P1 后 from_dict 行为不变，测试应通过
- `tests/test_rules.py`：不变（Input 方向未改，rules 接受 dict 不变）

---

## 未解决问题

1. ~~Strawberry pydantic 集成对 `list[str]` 字段的处理~~ → 已验证通过
2. ~~`GeoLocation` 嵌套 Optional 字段~~ → 已验证通过
3. P3 后 `WorkflowStagesGQL` 的 `JSON` 类型字段不受影响（纯 dict 传递），保持不变
4. ~~`_dict_to_gql_context` 中 `destination` 为 `GeoLocationGQL | None` 的处理~~ → 已验证通过
5. P3 Input 方向不可行（`Literal` 与 Strawberry Enum 不兼容），已记录原因并排除

## 回退策略

- P0~P2：独立变更，每个可单独 revert
- P3：如果 pydantic 集成有问题，保留 `converters.py` 中的转换函数，不删除 Input 类型定义。仅将 `converters.py` 独立文件作为 P0 的产出，P3 不实施。
