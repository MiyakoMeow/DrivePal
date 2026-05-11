# 第三批：P3 维护性 实现计划

**目标：** 4 项维护性改进：Config 验证函数、batch_generate semaphore、close_session 校验、shortcut 重复 postprocess。

**架构：** 四项完全独立，可并行。

---

### 任务 3.1：Config validate_settings()

**文件：** `app/memory/memory_bank/config.py`
**测试：** `tests/test_settings.py` 追加

加 `validate_settings()` 函数，显式检查关键配置参数，值无效时 raise ValueError。保持 `field_validator` fallback 行为不变。

```python
def validate_settings(config: MemoryBankConfig | None = None) -> list[str]:
    """校验配置参数，返回警告列表。值无效时仅 warn 不 raise（生产安全）。"""
    cfg = config or MemoryBankConfig()
    warnings: list[str] = []
    if not 0.0 < cfg.retrieval_alpha <= 1.0:
        warnings.append(f"retrieval_alpha={cfg.retrieval_alpha} 超出范围 (0,1]")
    if not 0.0 < cfg.soft_forget_threshold <= 1.0:
        warnings.append(f"soft_forget_threshold={cfg.soft_forget_threshold} 超出范围 [0,1]")
    if cfg.chunk_size is not None and not cfg.chunk_size_min <= cfg.chunk_size <= cfg.chunk_size_max:
        warnings.append(f"chunk_size={cfg.chunk_size} 超出 [{cfg.chunk_size_min}, {cfg.chunk_size_max}]")
    for w in warnings:
        logger.warning("Config warning: %s", w)
    return warnings
```

### 任务 3.2：batch_generate provider semaphore

**文件：** `app/models/chat.py`

```python
async def batch_generate(self, prompts: list[str], ...) -> list[str]:
    if not prompts:
        return []
    # 获取首个 provider 的 semaphore
    sem = await self._acquire_slot(self.providers[0])
    async def _bounded(p: str) -> str:
        async with sem:
            return await self.generate(p, system_prompt)
    return list(await asyncio.gather(*[_bounded(p) for p in prompts]))
```

### 任务 3.3：close_session 用户校验

**文件：** `app/agents/conversation.py`, `app/api/resolvers/mutation.py`

`ConversationManager` 中 `create()` 已记录 `user_id`。`close()` 加 `user_id` 参数校验。

```python
def close(self, session_id: str, user_id: str | None = None) -> bool:
    session = self._sessions.get(session_id)
    if session is None:
        return False
    if user_id is not None and session.get("user_id") != user_id:
        return False
    del self._sessions[session_id]
    return True
```

### 任务 3.4：shortcut 双重 postprocess

**文件：** `app/agents/workflow.py`

`_execution_node` 加检查：`decision.get("_postprocessed")` 则跳过 `postprocess_decision`。shortcut 路径设标记。
