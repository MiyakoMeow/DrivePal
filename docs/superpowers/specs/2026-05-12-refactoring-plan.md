# 知行车秘 系统重构计划

## 概述

对 `app/` 代码库进行全面代码审查后发现的 17 项问题（排除 1 项假阳、1 项非问题），按风险/影响分三批增量修复。

**分析报告**：详见 `.worktrees/analysis/` 工作树中的分析记录。

**分批策略**：P1（功能缺陷）→ P2（架构加固）→ P3（维护性）。每批独立 PR。

---

## 第一批：功能缺陷（P1）

### 1.1 SSE 流式改造

**问题**：`app/agents/workflow.py:run_stream()` 先计算全部阶段再批量返回事件列表，SSE 端点首字节延迟等于全部 LLM 调用时间之和。

**方案**：`run_stream()` 改 `AsyncGenerator`，每阶段完成后立即 yield。

**改动文件**：
- `app/agents/workflow.py` — `run_stream` 签名改为 `async def run_stream(...) -> AsyncGenerator[dict, None]`，每阶段 `yield event`。移除事件列表累加逻辑。
- `app/api/stream.py` — 调用方改为 `async for event in workflow.run_stream(...)` 逐条 SSE 推送。

**边界条件**：
- 异常中断：generator 内 `try/finally` 保证 `event: error` 事件发出
- 半完成状态：generator 中途异常时，已 yield 的事件已发送到客户端
- SSE HTTP 连接断开：FastAPI StreamingResponse 自动处理

**回归**：不影响 `run_with_stages()`。

### 1.2 FAISS 加载非阻塞

**问题**：`app/memory/memory_bank/index.py:FaissIndex.load()` 中 `faiss.read_index()` 是同步磁盘 I/O，在 async 方法中直接调用，大索引阻塞事件循环。

**方案**：`faiss.read_index()` 通过 `asyncio.get_event_loop().run_in_executor(None, ...)` 执行。所有 `os.path.exists` / `read_text` / `shutil.copy` 等同步文件操作一并包装。

**改动文件**：
- `app/memory/memory_bank/index.py`

**边界条件**：
- 索引文件极小（空/新索引）无瓶颈，包装开销可忽略
- 多并发 load 场景：`asyncio.Lock` 序列化

### 1.3 update_feedback 并发保护

**问题**：`app/memory/memory_bank/lifecycle.py:update_feedback()` 直接 mutate `self._index.get_metadata_by_id(fid)` 返回的 dict，无锁保护。

**方案**：加 `asyncio.Lock` 保护 memory_strength / last_recall_date 的读-改-写序列。锁作用于 `MemoryLifecycle` 实例级别。

**改动文件**：
- `app/memory/memory_bank/lifecycle.py` — 加 `_feedback_lock: asyncio.Lock`

### 1.4 feedback 受 max_memory_strength 上限约束

**问题**：`lifecycle.py:update_feedback()` 做 `old_strength + 2.0` 不做上限检查；检索管道的 `_update_memory_strengths()` 已有 `min(..., max_memory_strength)`，feedback 路径遗漏。

**方案**：`update_feedback()` 中 `old_strength + 2.0` → `min(old_strength + 2.0, config.max_memory_strength)`。

**改动文件**：
- `app/memory/memory_bank/lifecycle.py`

---

## 第二批：架构加固（P2）

### 2.1 LLM JSON 输出结构化验证

**问题**：`LLMJsonResponse` 使用 `extra="allow"`，任何 JSON 输出均无结构验证。各阶段输出期望字段无模型约束。

**方案**：为 Context/Task/Strategy 三阶段分别建输出模型（继承 Pydantic BaseModel, `extra="forbid"`）：
- `ContextOutput` — fields: scenario, driver_state, spatial, traffic, current_datetime, related_events, conversation_history (optional)
- `TaskOutput` — fields: type, confidence, description, entities (optional)
- `StrategyOutput` — fields: should_remind, timing, target_time, delay_seconds, reminder_content, type, reason, allowed_channels, action (optional)
- `LLMJsonResponse` 改为 `extra="forbid"`，仅在解析失败时走兜底

各节点在 `_call_llm_json` 后通过 `model_validate()` 校验，校验失败 log warning 后仍用 `raw` 尝试提取，保证 LLM 降级时系统不崩溃。

**改动文件**：
- `app/agents/workflow.py` — 新增输出模型定义，`_call_llm_json` 注入校验
- `app/agents/prompts.py` — 提示词加字段约束描述（可选，不影响兼容性）

**测试策略**：
- 有效 JSON 通过验证
- 缺失字段 / 额外字段拒绝验证并回退
- `LLMJsonResponse.from_llm()` 兜底路径覆盖

### 2.2 AgentState 类型安全

**问题**：`AgentState` 为裸 `dict`，节点间用字符串 key 约定传递数据，IDE 不支持/重构不可靠。

**方案**：`state.py` 中定义 `AgentState(TypedDict)`，含 `original_query`, `context`, `task`, `decision`, `result`, `event_id`, `driving_context`, `stages`, `session_id`。设 `NotRequired` 用于中间态。

**改动文件**：
- `app/agents/state.py` — 从 `dict` 改为 `TypedDict`
- `app/agents/workflow.py` — 类型标注更新
- `tests/*` — 测试用例 `AgentState` 构造改为 TypedDict

### 2.3 _ensure_loaded 懒加载优化

**问题**：`MemoryBankStore` 每操作调用 `_ensure_loaded()`，首次加载后仍做 async 开销。

**方案**：加 `_loaded: bool` 标志位，首次 `load()` 成功后设为 True，后续跳过。

**改动文件**：
- `app/memory/memory_bank/store.py`

### 2.4 合并结果静默丢弃

**问题**：`_merge_result_group()` 处理空文本时返回 None，调用方不计数。

**方案**：`_merge_result_group()` 返回 None 时，在 `_merge_overlapping_results` 中调用 `metrics.forget_count += 1`（复用 forget_count 字段，语义为"丢弃计数"）加 `logger.warning`。最小改动，不改 search 返回签名。

**改动文件**：
- `app/memory/memory_bank/retrieval.py`
- `app/memory/memory_bank/observability.py` — 字段注释调整

### 2.5 旧平铺迁移简化

**问题**：`init_data.py` 中三层嵌套迁移函数处理一次性迁移场景，每次启动扫描磁盘。

**方案**：加 `_migrated` sentinel 文件（`data/.migrated_flag`），存在则跳过全部迁移代码。不移除迁移函数（向后兼容旧数据目录）。

**改动文件**：
- `app/storage/init_data.py`

---

## 第三批：维护性（P3）

### 3.1 Config 验证 raise 模式

**问题**：`MemoryBankConfig` 的 `field_validator` 在无效值时全部静默 fallback，仅 log warning。用户设错参数无反馈。

**方案**：保持 fallback 行为不变（生产健壮性），新增 `validate_settings()` 函数（可在启动时或 CLI 调用），显式检查各参数并 `raise` 或 `warnings.warn`。测试中写用例覆盖各边界。

**改动文件**：
- `app/memory/memory_bank/config.py` — 加 `validate_settings()` 函数

### 3.2 batch_generate 使用 provider semaphore

**问题**：`ChatModel.batch_generate()` 硬编码 `Semaphore(8)`，绕过了 provider 级别的并发控制。

**方案**：`batch_generate` 中获取首个 provider 的 semaphore 并用于所有并发请求。单 provider 场景（常见）行为正确。多 provider 场景暂不做完美分发——用例稀少，且首次 provider 的 semaphore 已能抑制总并发。若未来多 provider batch 变常见再优化。

**改动文件**：
- `app/models/chat.py`

### 3.3 close_session 用户校验

**问题**：`close_session` mutation 接受 `session_id` 和 `current_user`，但不校验 session 是否属于该用户。

**方案**：`ConversationManager.close()` 加 `user_id` 参数校验。找不到匹配合话则静默成功（安全）。

**改动文件**：
- `app/agents/conversation.py`
- `app/api/resolvers/mutation.py`

### 3.4 shortcut 路径双重 postprocess

**问题**：`run_with_stages()` 的 shortcut 路径先 `postprocess_decision`，然后 `_execution_node`（对全流水线路径）在 `state.get("driving_context")` 存在时再调一次 `postprocess_decision`。shortcut 路径中虽然传了 `shortcut_decision` 而非全流水线 `state["decision"]`，但 `_execution_node` 从 `state.get("decision")` 读取，shortcut 路径已设好，因此确实触发两次。但后一次是对同一 decision 再应用相同约束，幂等故无功能问题。

**方案**：`_execution_node` 加检查：若 `decision` 已经有 `_postprocessed: true` 标记则跳过。shortcut 路径设置此标记。

**改动文件**：
- `app/agents/workflow.py`



---

## 依赖关系

```
Batch 1 ──→ Batch 2 ──→ Batch 3
              │
              └── 2.3（_ensure_loaded）依赖 1.2（FAISS 加载优化）
```

批内项可并行（如 1.3 + 1.4 同在 lifecycle.py，可一次改完）。

## 不修项（已排除）

| 原# | 问题 | 排除理由 |
|-----|------|---------|
| 2 | close() save 重复 | 实际逻辑正确，非冗余 |
| 11 | metrics list 无限增长 | 实为 `deque(maxlen=1000)`，受控 |
| 12 | TOMLStore 引用分散 | 实例中已有保存 |
| 16 | 加 correlation ID | 当前日志量小，收益不足以覆盖改动成本 |

## 测试策略

每项改动要求：
1. 已有测试全绿
2. 新增测试覆盖新行为 + 边界 + 异常路径
3. 运行 `uv run ty check` 确保类型安全

## 参考

- 分析记录：`app/agents/workflow.py` 注释（run_stream 自我批评）
- 并发锁模式：`app/memory/memory_bank/store.py` `_source_index_lock` 先例
- SSE 规范：`app/api/stream.py` 现有实现
