# EmbeddingModel 独立性改造设计

**日期**: 2026-03-28
**状态**: 已批准

## 背景

当前 `EmbeddingModel` 依赖 `LLMSettings.load()` 来获取 embedding providers。当无 LLM 配置（CI 环境）时，`LLMSettings.load()` 抛出 `RuntimeError`。

`EmbeddingModel.__init__` 的异常处理逻辑：
- `device is not None` → fallback 到本地 HuggingFace 模型
- `device is None` → 重新抛出异常

这导致 `get_embedding_model(device=None)` 在 CI 环境中无法工作，进而影响依赖 embedding 的 store 创建。

## 设计目标

使 `EmbeddingModel` 在无 LLM 配置时也能正常工作（使用本地 HuggingFace fallback），不依赖 API key 或远程 endpoint。

## 方案 C：默认 CPU Fallback

### 改动点

**文件**: `app/models/embedding.py` 第 44-55 行

**修改前**:
```python
if providers is None:
    try:
        settings = LLMSettings.load()
        providers = settings.embedding_providers
    except RuntimeError:
        if device is not None:
            providers = [
                EmbeddingProviderConfig(
                    model="BAAI/bge-small-zh-v1.5", device=device
                )
            ]
        else:
            raise
```

**修改后**:
```python
if providers is None:
    try:
        settings = LLMSettings.load()
        providers = settings.embedding_providers
    except RuntimeError:
        providers = [
            EmbeddingProviderConfig(
                model="BAAI/bge-small-zh-v1.5", device=device or "cpu"
            )
        ]
```

### 行为变化

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 有 LLM 配置 | 使用配置的 providers | 不变 |
| 无 LLM 配置 + device="cuda" | fallback cuda | 不变 |
| 无 LLM 配置 + device=None | **抛异常** | fallback cpu |

## 影响范围

- `MemoryModule._create_store` 对 embedding stores 的创建不再需要显式传 `device`
- `get_embedding_model(device=None)` 在任何环境下都能返回一个可用的 `EmbeddingModel`
- CI 测试中 embedding 相关的测试可以正常运行，不再需要 `@SKIP_IF_NO_LLM`

## 后续任务

1. 修改 `app/models/embedding.py` 实现上述改动
2. 运行 CI 检查确认不影响现有功能
3. 考虑简化 `test_memory_store_contract.py` 的动态 mode 切换逻辑
