# 移除内置 Embeddings 模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除所有本地 embeddings 推理逻辑和依赖，统一使用 OpenAI 兼容远程 API。

**Architecture:** 简化 `EmbeddingModel` 类为纯 OpenAI 客户端封装，移除 SentenceTransformer/torch 相关代码，清理配置、依赖和 Nix 环境。

**Tech Stack:** openai (AsyncOpenAI), pytest, ruff, ty

---

### Task 1: 简化 `app/models/embedding.py`

**Files:**
- Modify: `app/models/embedding.py`

- [ ] **Step 1: 重写 `embedding.py`，移除所有本地模型逻辑**

将文件内容替换为以下（保留模块 docstring 和缓存机制，移除 torch/SentenceTransformer）：

```python
"""文本嵌入模型封装，仅支持 OpenAI 兼容远程接口."""

from typing import TYPE_CHECKING

import openai

from app.models.settings import EmbeddingProviderConfig, LLMSettings, ProviderConfig

if TYPE_CHECKING:
    pass

_EMBEDDING_MODEL_CACHE: dict[str, EmbeddingModel] = {}


def get_cached_embedding_model() -> EmbeddingModel:
    """获取缓存的embedding模型实例，避免重复加载."""
    settings = LLMSettings.load()
    provider = settings.get_embedding_provider()
    if provider is None:
        msg = "No embedding provider configured"
        raise RuntimeError(msg)
    model = provider.provider.model
    base_url = provider.provider.base_url or ""
    cache_key = f"{model}|{base_url}"
    if cache_key not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[cache_key] = EmbeddingModel(provider=provider)
    return _EMBEDDING_MODEL_CACHE[cache_key]


def clear_embedding_model_cache() -> None:
    """清除embedding模型缓存."""
    _EMBEDDING_MODEL_CACHE.clear()


class EmbeddingModel:
    """文本嵌入模型封装，支持单provider."""

    def __init__(
        self,
        provider: EmbeddingProviderConfig | None = None,
    ) -> None:
        """初始化嵌入模型."""
        if provider is None:
            try:
                settings = LLMSettings.load()
                provider = settings.get_embedding_provider()
            except RuntimeError:
                pass
        if provider is None:
            msg = "Embedding provider is required (no local model fallback)"
            raise RuntimeError(msg)
        self.provider = provider
        self._client: openai.AsyncOpenAI | None = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        """获取或延迟创建嵌入模型客户端."""
        if self._client is not None:
            return self._client
        self._client = self._create_client(self.provider)
        return self._client

    def _create_client(
        self,
        provider: EmbeddingProviderConfig,
    ) -> openai.AsyncOpenAI:
        """创建嵌入模型客户端."""
        kwargs: dict = {"api_key": provider.provider.api_key or "not-needed"}
        kwargs["base_url"] = provider.provider.base_url
        return openai.AsyncOpenAI(**kwargs)

    async def _async_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        text: str,
    ) -> list[float]:
        """使用openai异步接口编码文本."""
        resp = await client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    async def _async_batch_encode_with_openai(
        self,
        client: openai.AsyncOpenAI,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """使用openai异步接口批量编码文本."""
        resp = await client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]

    async def encode(self, text: str) -> list[float]:
        """编码文本为向量."""
        return await self._async_encode_with_openai(
            self.client,
            self.provider.provider.model,
            text,
        )

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本为向量."""
        return await self._async_batch_encode_with_openai(
            self.client,
            self.provider.provider.model,
            texts,
        )


def reset_embedding_singleton() -> None:
    """清除缓存并重置为初始状态（供测试使用）."""
    _EMBEDDING_MODEL_CACHE.clear()
```

- [ ] **Step 2: 验证语法**

Run: `uv run python -c "import ast; ast.parse(open('app/models/embedding.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/models/embedding.py
git commit -m "refactor: remove local SentenceTransformer from EmbeddingModel"
```

---

### Task 2: 清理 `app/models/settings.py` 中的 `device` 字段

**Files:**
- Modify: `app/models/settings.py:84-95` (EmbeddingProviderConfig)
- Modify: `app/models/settings.py:205-212` (get_embedding_provider)

- [ ] **Step 1: 移除 `EmbeddingProviderConfig.device` 字段和 `from_dict` 中的 `device` 提取**

将 `EmbeddingProviderConfig` 类（约第 84-95 行）替换为：

```python
@dataclass
class EmbeddingProviderConfig:
    """单个 Embedding 服务提供商配置."""

    provider: ProviderConfig

    @classmethod
    def from_dict(cls, d: dict) -> EmbeddingProviderConfig:
        """从字典创建配置实例."""
        provider, _extra = _build_provider_config_from_dict(d, {})
        return cls(provider=provider)
```

- [ ] **Step 2: 移除 `get_embedding_provider()` 中的 `device` 传参**

将 `get_embedding_provider()` 方法（约第 190-212 行）的 return 语句替换为：

```python
        return EmbeddingProviderConfig(
            provider=ProviderConfig(
                model=resolved.model_name,
                base_url=provider_config.get("base_url"),
                api_key=api_key,
            ),
        )
```

- [ ] **Step 3: 验证语法**

Run: `uv run python -c "import ast; ast.parse(open('app/models/settings.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/models/settings.py
git commit -m "refactor: remove device field from EmbeddingProviderConfig"
```

---

### Task 3: 更新 `config/llm.toml`

**Files:**
- Modify: `config/llm.toml`

- [ ] **Step 1: 替换 embedding 配置和移除 huggingface provider**

将文件末尾的：

```toml
[embedding]
model = "huggingface/BAAI/bge-small-zh-v1.5"

[model_providers.huggingface]
```

替换为：

```toml
[embedding]
model = "openai/text-embedding-3-small"
```

注意：`[model_providers.openai]` 需要已存在于配置中，或在此添加。当前配置中 openai provider 不存在，需要新增。在文件中 `model_providers` 部分添加：

```toml
[model_providers.openai]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

- [ ] **Step 2: Commit**

```bash
git add config/llm.toml
git commit -m "refactor: switch embedding config from huggingface to openai"
```

---

### Task 4: 清理 `pyproject.toml` 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 移除 torch 相关依赖和 uv 源配置**

将 `dependencies` 列表中的三行移除：
```
"sentence-transformers>=5.3.0",
"torch>=2.11.0",
"torchvision>=0.26.0",
```

移除整个 `[[tool.uv.index]]` 段：
```toml
[[tool.uv.index]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

将 `[tool.uv.sources]` 段替换为空（移除 torch/torchvision 源）：
```toml
[tool.uv.sources]
```

如果 `[tool.uv.sources]` 为空且没有其他条目，可直接移除该段。

- [ ] **Step 2: 重新同步 lock 文件**

Run: `uv lock`
Expected: 成功，lock 文件更新

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: remove torch/sentence-transformers dependencies"
```

---

### Task 5: 清理 `flake.nix` CUDA 配置

**Files:**
- Modify: `flake.nix`

- [ ] **Step 1: 移除 CUDA 相关配置**

将 `flake.nix` 的 `outputs` 部分替换为：

```nix
  outputs =
    { nixpkgs, pyproject-nix, ... }:
    let
      project = pyproject-nix.lib.project.loadPyproject {
        projectRoot = ./.;
      };

      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      python = pkgs.python314;
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = [
          python
          pkgs.uv
        ];

        env = {
          UV_PYTHON = python.interpreter;
          UV_NO_SYNC = "1";
          UV_PYTHON_DOWNLOADS = "never";
        };

        shellHook = ''
          unset PYTHONPATH
          export REPO_ROOT=$(git rev-parse --show-toplevel)
          export LD_LIBRARY_PATH="${
            pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]
          }:$LD_LIBRARY_PATH"
        '';
      };
    };
```

- [ ] **Step 2: Commit**

```bash
git add flake.nix
git commit -m "build: remove CUDA config from flake.nix"
```

---

### Task 6: 清理测试文件 `tests/test_settings.py`

**Files:**
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 移除 `TestEmbeddingProviderConfig.test_from_dict_local`**

删除 `test_from_dict_local` 方法（约第 80-91 行）。

- [ ] **Step 2: 修改 `test_load_from_config_file` 中的 huggingface 引用**

将该测试（约第 109-137 行）中的配置数据从：
```python
"huggingface": {},
"embedding": {"model": "huggingface/bge-test"},
```
替换为：
```python
"openai": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-test",
},
"embedding": {"model": "openai/text-embedding-3-small"},
```

并将断言从 `assert settings.embedding_model == "huggingface/bge-test"` 改为 `assert settings.embedding_model == "openai/text-embedding-3-small"`。

- [ ] **Step 3: 移除 `test_get_embedding_provider_local`**

删除整个 `test_get_embedding_provider_local` 方法。

- [ ] **Step 4: 移除 `test_get_embedding_provider_with_device_override`**

删除整个 `test_get_embedding_provider_with_device_override` 方法。

- [ ] **Step 5: 移除 `test_local_provider_creates_sentence_transformer`**

删除 `TestEmbeddingModelFallback` 类中的 `test_local_provider_creates_sentence_transformer` 方法。

- [ ] **Step 6: 修改 `test_encode_uses_client` 的 mock 方式**

将该方法（约第 439-452 行）替换为：

```python
    async def test_encode_uses_client(self) -> None:
        """验证 encode 委托给 openai 客户端."""
        provider = EmbeddingProviderConfig(
            provider=ProviderConfig(
                model="text-embedding-3-small",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            ),
        )
        emb = EmbeddingModel(provider=provider)
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock()]
        mock_resp.data[0].embedding = [0.1, 0.2, 0.3]
        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_resp)
        emb._client = mock_client
        result = await emb.encode("test")
        assert result == [0.1, 0.2, 0.3]
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_settings.py
git commit -m "test: update embedding tests for OpenAI-only mode"
```

---

### Task 7: 更新 `DEV.md` 文档

**Files:**
- Modify: `DEV.md`

- [ ] **Step 1: 更新 embedding 配置示例和技术栈**

将 `DEV.md` 第 29-30 行的：
```toml
[embedding]
model = "huggingface/BAAI/bge-small-zh-v1.5"
```
替换为：
```toml
[embedding]
model = "openai/text-embedding-3-small"
```

将第 185 行的：
```
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
```
替换为：
```
| **嵌入模型** | OpenAI text-embedding-3-small |
```

- [ ] **Step 2: Commit**

```bash
git add DEV.md
git commit -m "docs: update embedding references in DEV.md"
```

---

### Task 8: 运行完整验证

**Files:** 无修改

- [ ] **Step 1: 运行 ruff check**

Run: `uv run ruff check --fix`
Expected: 无错误

- [ ] **Step 2: 运行 ruff format**

Run: `uv run ruff format`
Expected: 无格式问题

- [ ] **Step 3: 运行 ty 类型检查**

Run: `uv run ty check`
Expected: 无类型错误

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/ -v --timeout=60 -x`
Expected: 所有测试通过

- [ ] **Step 5: 最终 Commit（如有自动修复产生的变更）**

```bash
git add -A
git commit -m "chore: lint and format fixes after embedding refactor"
```
（仅在有变更时执行）
