# 知行车秘

## 项目配置

- 使用`uv`。

- 检查配置：[详见CI](.github/workflows/python.yml)
  - 每次修改后，直接运行，不要加额外参数：
    1. `uv run ruff check --fix`
    2. `uv run ruff format`
    3. `uv run ty check`
  - 任务完成后：
    1. 额外运行CI中的 `test` 检查，详细验证无功能破坏。
  - 注意：
    1. 本项目的类型检查器，使用 `ty` 。[官方文档](https://docs.astral.sh/ty/)

## 代码规范

### 代码注释

- 必须使用中文。

### 提交信息

- 必须使用英文。
- 必须遵循 Conventional Commits 规范。

### PEP参考

- PEP 585 — 标准集合泛型语法
  - 用 `list[int]`、`dict[str, int]`、`tuple[int, ...]` 替代 `typing.List`、`typing.Dict`、`typing.Tuple`
  - 用 `collections.abc.Callable`、`collections.abc.Iterator` 等替代 `typing.Callable`、`typing.Iterator`
  - 禁止从 `typing` 导入已弃用的 `List`、`Dict`、`Set`、`Tuple`、`FrozenSet`、`Type` 等

- PEP 604 — 联合类型新语法
  - 用 `int | str` 替代 `Union[int, str]`；用 `int | None` 替代 `Optional[int]`
  - 可用于 `isinstance(x, int | str)` 和 `issubclass(cls, int | float)` 运行时检查

- PEP 649 — 注解延迟求值
  - 3.14+ 默认行为，注解访问 `__annotations__` 时才求值，无需 `from __future__ import annotations`
  - 前向引用直接写 `def foo(x: MyType) -> int:` 无需引号；注解中禁止 `:=`、`yield`、`await`
  - 用 `typing.get_type_hints()` 或 `inspect.get_annotations()` 获取注解

- PEP 654 — 异常组与 except*
  - `ExceptionGroup("msg", [err1, err2])` 打包多个不相关异常
  - `except* ValueError as eg:` 处理特定类型，`eg` 仍是 `ExceptionGroup`，可触发多个 `except*` 块
  - `except` 与 `except*` 不可混用；`except*` 块中禁止 `return`、`break`、`continue`

- PEP 695 — 类型参数语法
  - `class Map[K, V]:` 替代 `class Map(Generic[K, V]):`；`def f[T](x: T) -> T:` 替代 `TypeVar`
  - `type Alias[T] = list[T] | set[T]` 替代 `TypeAlias`；`[T: Comparable]` 上界；`[T: (str, bytes)]` 约束
  - 方差自动推断；新语法与传统 `TypeVar` 不可混用

- PEP 758 — except/except* 无括号语法
  - 无 `as` 时可省略括号：`except ValueError, TypeError:` 等价于 `except (ValueError, TypeError):`
  - 有 `as` 时仍需括号：`except (ValueError, TypeError) as e:` 不允许省略
  - 同样适用于 `except*`：`except* ValueError, TypeError:` 合法

## 注意事项

- 禁止修改 `vendor` 目录下的 `VehicleMemBench` 子模块中的文件。

