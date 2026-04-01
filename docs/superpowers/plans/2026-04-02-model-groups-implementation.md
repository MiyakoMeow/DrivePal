# Model Groups 配置架构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `model_groups` + `model_providers` 分层配置架构，支持按名称动态选择模型组

**Architecture:** 在 `adapters/model_config.py` 新增模型解析函数，在 `app/models/settings.py` 新增 `model_groups` 支持，保持向后兼容

**Tech Stack:** Python, tomllib, dataclass

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `adapters/model_config.py` | 新增 `resolve_model_string`、`_resolve_provider`、`get_model_group_providers` |
| `app/models/settings.py` | 新增 `ResolvedModel` dataclass、`LLMSettings.model_groups`、`get_model_group_providers` |
| `tests/test_adapters/test_model_config.py` | 新增 `resolve_model_string` 和 `get_model_group_providers` 测试 |
| `tests/test_settings.py` | 新增 model_groups 相关测试 |

---

## Task 1: 新增 `ResolvedModel` dataclass

**Files:**
- Modify: `app/models/settings.py:1-15`

- [ ] **Step 1: 添加 ResolvedModel dataclass**

在 `app/models/settings.py` 的 `ProviderConfig` 前添加:

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ResolvedModel:
    """解析后的模型引用."""
    provider_name: str
    model_name: str
    params: dict[str, Any]
```

- [ ] **Step 2: 运行类型检查**

Run: `uv run ty check app/models/settings.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/models/settings.py
git commit -m "feat(settings): add ResolvedModel dataclass"
```

---

## Task 2: 新增 `resolve_model_string` 函数

**Files:**
- Modify: `adapters/model_config.py:1-112`
- Reference: `app/models/settings.py` (已定义 `ResolvedModel`)

**说明:** `ResolvedModel` 定义在 `settings.py` 中，`model_config.py` 通过 import 引用。这是分层设计：底层返回 dict，高层封装为 typed dataclass。

- [ ] **Step 1: 添加 resolve_model_string 函数**

在 `adapters/model_config.py` 开头 `from typing import TYPE_CHECKING` 后添加:

```python
from app.models.settings import ResolvedModel
```

然后在文件末尾添加:

```python
def resolve_model_string(model_str: str) -> ResolvedModel:
    """解析模型引用 'provider/model?key=value' 格式.
    
    Args:
        model_str: 模型引用字符串，如 'deepseek/deepseek-chat?temperature=0.1'
        
    Returns:
        ResolvedModel 实例
        
    Raises:
        ValueError: 格式无效时
    """
    params: dict[str, Any] = {}
    if "?" in model_str:
        model_part, query_part = model_str.split("?", 1)
        for item in query_part.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                try:
                    params[key] = float(value) if "." in value else int(value)
                except ValueError:
                    params[key] = value
        model_str = model_part
    
    if "/" not in model_str:
        raise ValueError(f"Invalid model string format: {model_str}. Expected 'provider/model'")
    
    provider_name, model_name = model_str.split("/", 1)
    return ResolvedModel(provider_name=provider_name, model_name=model_name, params=params)
```

- [ ] **Step 2: 编写测试**

在 `tests/test_adapters/test_model_config.py` 末尾添加:

```python
def test_resolve_model_string_simple() -> None:
    """测试简单模型引用解析."""
    from adapters.model_config import resolve_model_string
    result = resolve_model_string("deepseek/deepseek-chat")
    assert result.provider_name == "deepseek"
    assert result.model_name == "deepseek-chat"
    assert result.params == {}


def test_resolve_model_string_with_params() -> None:
    """测试带参数的模型引用解析."""
    from adapters.model_config import resolve_model_string
    result = resolve_model_string("zhipuai-coding-plan/glm-4.7-flashx?temperature=0.1&max_tokens=1000")
    assert result.provider_name == "zhipuai-coding-plan"
    assert result.model_name == "glm-4.7-flashx"
    assert result.params == {"temperature": 0.1, "max_tokens": 1000}


def test_resolve_model_string_invalid_format() -> None:
    """测试无效格式."""
    from adapters.model_config import resolve_model_string
    with pytest.raises(ValueError, match="Invalid model string format"):
        resolve_model_string("invalid-format")
```

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/test_adapters/test_model_config.py::test_resolve_model_string_simple tests/test_adapters/test_model_config.py::test_resolve_model_string_with_params tests/test_adapters/test_model_config.py::test_resolve_model_string_invalid_format -v`
Expected: PASS (3 tests)

- [ ] **Step 4: 运行类型检查**

Run: `uv run ty check adapters/model_config.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/model_config.py tests/test_adapters/test_model_config.py
git commit -m "feat(model_config): add resolve_model_string function"
```

---

## Task 3: 新增 `_resolve_provider` 函数

**Files:**
- Modify: `adapters/model_config.py:113-130` (文件末尾)

- [ ] **Step 1: 添加 _resolve_provider 函数**

在 `adapters/model_config.py` 末尾 `get_store_embedding_model` 前添加:

```python
@lru_cache(maxsize=1)
def _load_config() -> dict:
    """从 TOML 文件加载配置（已缓存）."""
    config_path = _get_config_path()
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=1)
def _resolve_provider(provider_name: str) -> dict:
    """根据 provider 名称解析 provider 配置.
    
    Args:
        provider_name: provider 名称，对应 model_providers 中的表名
        
    Returns:
        provider 配置字典
        
    Raises:
        ValueError: provider 未配置时
    """
    config = _load_config()
    providers = config.get("model_providers", {})
    if provider_name not in providers:
        raise ValueError(f"Provider '{provider_name}' not found in model_providers")
    return providers[provider_name]


def get_model_group_providers(name: str) -> list[dict]:
    """按组名获取 LLMProviderConfig 字典列表（底层接口）.
    
    Args:
        name: 模型组名称
        
    Returns:
        LLMProviderConfig 字典列表
        
    Raises:
        KeyError: 模型组不存在时
    """
    config = _load_config()
    model_groups = config.get("model_groups", {})
    if name not in model_groups:
        raise KeyError(f"Model group '{name}' not found")
    
    model_refs = model_groups[name].get("models", [])
    if not model_refs:
        return []
    
    result = []
    for ref in model_refs:
        resolved = resolve_model_string(ref)
        provider_config = _resolve_provider(resolved.provider_name)
        api_key = os.environ.get(provider_config.get("api_key_env", ""), "")
        result.append({
            "model": resolved.model_name,
            "base_url": provider_config.get("base_url"),
            "api_key": api_key,
            "temperature": resolved.params.get("temperature", 0.7),
        })
    return result
```

- [ ] **Step 2: 运行类型检查**

Run: `uv run ty check adapters/model_config.py`
Expected: PASS (可能提示未使用缓存，需确认)

- [ ] **Step 3: Commit**

```bash
git add adapters/model_config.py
git commit -m "feat(model_config): add _resolve_provider and get_model_group_providers"
```

---

## Task 4: 新增 settings 中 model_groups 支持

**Files:**
- Modify: `app/models/settings.py:86-145`

- [ ] **Step 1: 添加 model_groups 字段到 LLMSettings**

修改 `LLMSettings` dataclass:

```python
@dataclass
class LLMSettings:
    """模型配置集合，包含 LLM 和 Embedding 提供商列表."""

    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_providers: list[EmbeddingProviderConfig] = field(default_factory=list)
    judge_provider: JudgeProviderConfig | None = None
    model_groups: dict[str, list[str]] = field(default_factory=dict)
```

- [ ] **Step 2: 修改 load 方法支持 model_groups**

在 `LLMSettings.load()` 方法中，加载完 embedding_providers 后添加:

```python
# 加载 model_groups
model_groups = config_data.get("model_groups", {})

# 向后兼容：将 [llm] 映射为 [model_groups.default]
if "llm" in config_data and "default" not in model_groups:
    llm_list = config_data["llm"]
    if isinstance(llm_list, dict):
        llm_list = [llm_list]
    model_groups["default"] = [item["model"] for item in llm_list if "model" in item]

# 向后兼容：将 [benchmark] 映射为 [model_groups.benchmark]
if "benchmark" in config_data and "benchmark" not in model_groups:
    benchmark_data = config_data["benchmark"]
    if isinstance(benchmark_data, dict):
        model_name = benchmark_data.get("model", "")
    else:
        model_name = str(benchmark_data) if benchmark_data else ""
    if model_name:
        model_groups["benchmark"] = [model_name]
```

然后修改 return 语句:

```python
return cls(
    llm_providers=deduped,
    embedding_providers=embedding_providers,
    judge_provider=judge_provider,
    model_groups=model_groups,
)
```

- [ ] **Step 3: 添加 get_model_group_providers 方法**

在 `LLMSettings` 类后添加:

```python
def get_model_group_providers(name: str) -> list[LLMProviderConfig]:
    """按组名获取 LLMProviderConfig 列表.
    
    Args:
        name: 模型组名称
        
    Returns:
        LLMProviderConfig 列表
        
    Raises:
        KeyError: 模型组不存在时
    """
    from adapters.model_config import get_model_group_providers as _get_group_providers
    
    configs = _get_group_providers(name)
    return [LLMProviderConfig.from_dict(c) for c in configs]
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_settings.py -v -k "model_group or default" --tb=short`
Expected: PASS

- [ ] **Step 5: 运行类型检查**

Run: `uv run ty check app/models/settings.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models/settings.py
git commit -m "feat(settings): add model_groups support with backward compatibility"
```

---

## Task 5: 集成测试

**Files:**
- Create: `tests/test_integration/test_model_groups.py`

- [ ] **Step 1: 编写集成测试**

```python
"""model_groups 集成测试."""
import tomli_w
from pathlib import Path

import pytest


def test_model_groups_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试基本的 model_groups 配置."""
    config = {
        "model_groups": {
            "smart": {"models": ["deepseek/deepseek-chat"]},
        },
        "model_providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    
    from adapters.model_config import _load_config, get_model_group_providers
    _load_config.cache_clear()
    
    providers = get_model_group_providers("smart")
    assert len(providers) == 1
    assert providers[0]["model"] == "deepseek-chat"
    assert providers[0]["base_url"] == "https://api.deepseek.com/v1"


def test_model_groups_with_query_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试带 query 参数的 model_groups."""
    config = {
        "model_groups": {
            "fast": {"models": ["zhipuai-coding-plan/glm-4.7-flashx?temperature=0.1"]},
        },
        "model_providers": {
            "zhipuai-coding-plan": {
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_env": "ZHIPU_API_KEY",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")
    
    from adapters.model_config import _load_config, get_model_group_providers
    _load_config.cache_clear()
    
    providers = get_model_group_providers("fast")
    assert len(providers) == 1
    assert providers[0]["model"] == "glm-4.7-flashx"
    assert providers[0]["temperature"] == 0.1


def test_model_groups_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不存在的 model_group."""
    config = {"model_groups": {}}
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    
    from adapters.model_config import _load_config, get_model_group_providers
    _load_config.cache_clear()
    
    with pytest.raises(KeyError):
        get_model_group_providers("nonexistent")


def test_backward_compatibility_llm_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试向后兼容：[llm] 自动映射为 [model_groups.default]."""
    config = {
        "llm": [
            {"model": "qwen3.5-2b", "base_url": "http://localhost:8000/v1", "api_key": "test"}
        ],
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    
    from adapters.model_config import _load_config
    _load_config.cache_clear()
    
    from app.models.settings import LLMSettings
    settings = LLMSettings.load()
    assert "default" in settings.model_groups
    assert "qwen3.5-2b" in settings.model_groups["default"]


def test_backward_compatibility_benchmark_to_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试向后兼容：[benchmark] 自动映射为 [model_groups.benchmark]."""
    config = {
        "benchmark": {
            "model": "MiniMax-M2.7",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env": "MINIMAX_API_KEY",
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    
    from adapters.model_config import _load_config
    _load_config.cache_clear()
    
    from app.models.settings import LLMSettings
    settings = LLMSettings.load()
    assert "benchmark" in settings.model_groups
    assert "MiniMax-M2.7" in settings.model_groups["benchmark"]


def test_empty_model_group_returns_empty_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试空 model_group 返回空列表."""
    config = {
        "model_groups": {
            "empty": {"models": []},
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    
    from adapters.model_config import _load_config, get_model_group_providers
    _load_config.cache_clear()
    
    providers = get_model_group_providers("empty")
    assert providers == []
```

- [ ] **Step 2: 运行集成测试**

Run: `uv run pytest tests/test_integration/test_model_groups.py -v`
Expected: PASS (6 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration/test_model_groups.py
git commit -m "test: add model_groups integration tests"
```

---

## Task 6: 最终验证

- [ ] **Step 1: 运行完整测试**

Run: `uv run pytest tests/test_adapters/test_model_config.py tests/test_settings.py tests/test_integration/test_model_groups.py -v`
Expected: ALL PASS

- [ ] **Step 2: 运行 lint**

Run: `uv run ruff check --fix && uv run ruff format && uv run ty check`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: implement model_groups configuration architecture"
```
