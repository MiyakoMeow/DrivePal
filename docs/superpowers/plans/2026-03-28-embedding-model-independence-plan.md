# EmbeddingModel 独立性改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改 `EmbeddingModel.__init__` 在无 LLM 配置且 device=None 时自动 fallback 到 cpu device 的本地 HuggingFace 模型，使 embedding 功能不依赖 API 配置。

**Architecture:** 修改 `EmbeddingModel.__init__` 的异常处理逻辑，当 `LLMSettings.load()` 失败且 `device is None` 时，使用 `"cpu"` 作为默认 device 创建本地 HuggingFace provider。

**Tech Stack:** Python, langchain-huggingface, langchain-openai

---

## 任务清单

### 任务 1: 修改 EmbeddingModel.__init__ fallback 逻辑

**Files:**
- Modify: `app/models/embedding.py:44-55`

- [ ] **Step 1: 读取当前 embedding.py 内容确认行号**

```bash
cat -n app/models/embedding.py | head -60
```

- [ ] **Step 2: 修改异常处理逻辑**

将:
```python
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

改为:
```python
except RuntimeError:
    providers = [
        EmbeddingProviderConfig(
            model="BAAI/bge-small-zh-v1.5", device=device or "cpu"
        )
    ]
```

- [ ] **Step 3: 提交改动**

```bash
git add app/models/embedding.py
git commit -m "fix: EmbeddingModel fallback to cpu when no LLM config"
```

---

### 任务 2: 运行 CI 检查

**Files:**
- Modify: `app/models/embedding.py`

- [ ] **Step 1: 运行 ruff check**

```bash
ruff check app/models/embedding.py
```
Expected: 无错误

- [ ] **Step 2: 运行 ruff format**

```bash
ruff format app/models/embedding.py --diff
```
Expected: 无 diff

- [ ] **Step 3: 运行 type check**

```bash
ty check app/models/embedding.py
```
Expected: 无错误

- [ ] **Step 4: 运行 pytest**

```bash
pytest tests/ -v --tb=short
```
Expected: 所有测试通过（部分因无 LLM 配置而跳过）

---

## 验证方法

1. 在无 `config/llm.json` 和无 `OPENAI_*`/`DEEPSEEK_*` 环境变量的情况下：
   ```python
   from app.models.embedding import EmbeddingModel
   model = EmbeddingModel()  # 应该成功，不抛异常
   vec = model.encode("hello")  # 应该返回向量
   ```

2. CI 全部通过
