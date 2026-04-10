# 移除内置 Embeddings 模型，统一使用 OpenAI Embeddings API

## 目标

彻底移除代码中所有本地 embeddings 推理逻辑（基于 `sentence-transformers` + `torch`），统一使用 OpenAI 兼容的远程 embeddings API。同时清理相关重量级依赖（`torch`、`torchvision`、`sentence-transformers`）和 CUDA 构建配置。

## 变更范围

### 1. `app/models/embedding.py` — 核心简化

**移除：**
- `import torch`
- `from sentence_transformers import SentenceTransformer`（TYPE_CHECKING 和运行时）
- `_auto_detect_device()` 函数
- `_encode_with_local()` 方法
- `_batch_encode_with_local()` 方法
- `EmbeddingModel.__init__` 中的 fallback 逻辑（provider 为 None 时默认创建本地 SentenceTransformer）
- `_create_client()` 中的 SentenceTransformer 分支

**保留/变更：**
- `_client` 类型从 `openai.AsyncOpenAI | SentenceTransformer | None` 简化为 `openai.AsyncOpenAI | None`
- `_create_client()` 只返回 `openai.AsyncOpenAI`
- `encode()` 和 `batch_encode()` 移除 `isinstance` 分支，直接走 OpenAI 路径
- `provider` 参数语义不变（仍通过 `EmbeddingProviderConfig` 传入）
- `get_cached_embedding_model()` 的 `cache_key` 从 `f"{model}|{base_url}|{device}"` 简化为 `f"{model}|{base_url}"`（移除 `device` 维度）

### 2. `app/models/settings.py` — 配置清理

- `EmbeddingProviderConfig`：移除 `device: str | None = None` 字段
- `EmbeddingProviderConfig.from_dict()`：`extra_fields` 从 `{"device": None}` 改为 `{}`（`_build_provider_config_from_dict` 为 LLM/Judge/Embedding 三方共用，各自传独立 `extra_fields`，此修改不影响 LLM 和 Judge 侧）
- `get_embedding_provider()`：移除 `device=resolved.params.get("device")` 传参
- `get_embedding_model()` 和 `get_chat_model()`：保持不变

### 3. `config/llm.toml` — 配置文件

- 移除 `[model_providers.huggingface]`（空配置）
- `[embedding]` 改为引用远程 provider，如 `model = "openai/text-embedding-3-small"`
- 需要在 `[model_providers]` 中确保有对应的远程 provider 配置

### 4. `pyproject.toml` — 依赖清理

移除以下依赖项：
- `sentence-transformers>=5.3.0`
- `torch>=2.11.0`
- `torchvision>=0.26.0`

移除以下配置段：
- `[[tool.uv.index]]`（pytorch index）
- `[tool.uv.sources]` 中的 torch/torchvision 源

保留以下依赖项（尽管当前主代码未直接 import，但可能为 vendor 适配器或其他未来用途保留）：
- `datasets>=4.8.4`
- `huggingface-hub>=1.8.0`

### 5. `flake.nix` — Nix 环境清理

- 移除 `cudaLibs` 绑定和 `cudaPackages_12_8` 引用
- 移除 `shellHook` 中的 `LD_LIBRARY_PATH` CUDA 库路径设置
- 保留 `python314` + `uv` + `stdenv.cc.cc.lib`（基础 C 运行时）

### 6. 测试文件

**`tests/test_settings.py`：**
- 移除 `TestEmbeddingProviderConfig.test_from_dict_local`（本地 HuggingFace 解析测试）
- 移除 `TestLLMSettingsLoad.test_get_embedding_provider_local`（本地 embedding provider 测试）
- 移除 `TestLLMSettingsLoad.test_get_embedding_provider_with_device_override`（device 参数测试）
- 保留 `TestLLMSettingsLoad.test_get_embedding_provider_remote`
- 修改 `TestLLMSettingsLoad.test_load_from_config_file`：将 `huggingface` provider 和 `huggingface/bge-test` 替换为远程 provider（如 `openai`），保持测试语义一致
- 移除 `TestEmbeddingModelFallback.test_local_provider_creates_sentence_transformer`
- 保留 `TestEmbeddingModelFallback.test_remote_provider_creates_async_openai`
- 保留 `TestEmbeddingModelFallback.test_encode_uses_client`，调整 mock 方式：
  - 移除 `device="cpu"` 参数
  - `mock_client` 改为 AsyncOpenAI 风格：`mock_client.embeddings.create` 返回带有 `data[0].embedding` 的 AsyncMock
  - 或直接 mock `EmbeddingModel` 的 `_async_encode_with_openai` 方法

**`tests/test_embedding.py`：** 不变（仅依赖 `EmbeddingModel` 接口，不涉及本地/远程分支）

**`tests/conftest.py`：** 不变

### 7. 文档更新

- `DEV.md`：更新其中 `huggingface/BAAI/bge-small-zh-v1.5` 相关引用为远程 provider 配置

### 8. 不处理的文件

以下文件不在本次变更范围内：
- `vendor/VehicleMemBench/requirements.txt`（含 `sentence-transformers>=2.7.0`）：vendor 目录独立管理，不在主项目构建链中
- `test_memory_bank_dedup.py`（项目根目录）：import 了不存在的 `app.models.config` 模块，与本次变更无关的已有问题
- `BENCHMARK-VehicleMemBench.md`：HuggingFace 数据集链接与 provider 无关

### 9. 无需改动的文件

以下文件仅通过 TYPE_CHECKING 或延迟 import 引用 `EmbeddingModel`，接口不变，无需改动：
- `app/memory/singleton.py`
- `app/memory/memory.py`
- `app/memory/stores/memory_bank/engine.py`
- `app/memory/stores/memory_bank/store.py`
- `vendor_adapter/VehicleMemBench/model_config.py`
- `app/models/model_string.py`

## 约束

- embedding 配置**必须**通过远程 provider 指定 `base_url`，否则运行时报错
- 不再支持离线 embedding 推理
- 移除后 `uv.lock` 需要重新同步

## 成功标准

1. `sentence-transformers`、`torch`、`torchvision` 不再出现在 `pyproject.toml` 依赖中
2. 代码中不存在 `SentenceTransformer`、`torch` 的 import
3. `EmbeddingModel` 只使用 `openai.AsyncOpenAI` 客户端
4. 所有现有测试通过（移除本地模型相关测试后）
5. `uv run ruff check --fix`、`uv run ruff format`、`uv run ty check` 通过
