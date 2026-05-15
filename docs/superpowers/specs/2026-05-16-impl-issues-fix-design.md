# 实现问题修复设计

## 背景

项目全量分析发现 13 项实现问题（3 严重、4 中等、6 轻微）。设计目标全部达成，但实现层面存在异常处理矛盾、职责分散、状态管理不一致等问题。

## 范围

排除配置管理统一（CORS 配置化、配置来源统一、配置管理层）。

## 修改项

### S1. 工具异常修复

**问题**：`executor.py` 包装所有异常为 `ToolExecutionError(AppError)` → `workflow.py` re-raise AppError 子类 → 工具失败中断后续执行。与"不抛"设计矛盾。

**方案**：
- `executor.py` `execute()` 三档异常处理：
  - `AppError` 子类：原样 raise
  - `ValueError`/`TypeError`：包装为 `ToolExecutionError`
  - 其余 `Exception`：包装为 `ToolExecutionError`
- `workflow.py` `_handle_tool_calls`：
  - `except ToolExecutionError`：追加错误文本，继续循环
  - `except WorkflowError`：re-raise（工作流级错误）
  - `except AppError`：re-raise（域内错误）

### S2. postprocess 统一

**问题**：`postprocess_decision` 三处调用分散（`_execution_node`、shortcut、`proactive_run`），每处 `_postprocessed` flag 处理不同。

**方案**：提取 `_ensure_postprocessed(state)` 方法，三处调用统一走此方法。

### S3. 疲劳阈值统一

**问题**：`scheduler.py` 硬编码 `_FATIGUE_HIGH = 0.7`，`rules.py` 从配置读 `FATIGUE_THRESHOLD`。

**方案**：`rules.py` 导出 `get_fatigue_threshold()`。`scheduler.py` 删除 `_FATIGUE_HIGH`，import 并使用之。

### M4. Memory 检索拆读写

**问题**：`retrieval.py` `search()` 检索时原地修改 metadata（`memory_strength`/`last_recall_date`）。

**方案**：`search()` 纯读。新增 `apply_recall_boost(memory_ids, now)` 显式更新。调用方在 search 后调用。

### M5. 遗忘返回变更集

**问题**：`ForgettingCurve.maybe_forget()` 原地修改 FAISS metadata 引用。

**方案**：返回 `dict[str, dict]`（entry_id → changed fields）。`lifecycle.py` 接收变更集统一 apply。

### M6. 移除 `_source_event_index`

**问题**：`store.py` 维护内存 dict + FAISS metadata 双重状态。

**方案**：删除 `_source_event_index` dict 及维护代码。按 source date 查询时从 FAISS metadata 遍历。

### M7. pending 跳过 LLM

**问题**：`_poll_pending` 对已确定内容的 reminder 仍过完整三阶段工作流。

**方案**：reminder 已有完整内容时，构造 `WorkflowStages` 跳过前两阶段，仅执行 `_execution_node`。

### L8. _execution_node 拆分

**问题**：63 行，含 cancel/postpone/immediate/frequency guard/tool calls 五个分支。

**方案**：提取 `_should_send_reminder()`、`_execute_tool_calls()` 辅助方法。

### L9. 帧大小动态计算

**问题**：`pipeline.py` 硬编码 30ms 帧时长。

**方案**：从 VAD config 读 `frame_ms` 计算实际帧时长。

### L10. 删除 format_constraints() 死代码

`rules.py` L243-258 无调用方。

### L11. 删除 _extract_location_target 死参数

`workflow.py` L185 `_decision` 参数未使用。

### L12. _memory_module_state 封装修复

`main.py` 用 `get_memory_module()` 替代 `_memory_module_state[0]`。

### L13. logging.basicConfig 移除

模块级 `logging.basicConfig` 移入 `app.config`。

## 影响范围

| 模块 | 文件 | 变更类型 |
|------|------|----------|
| agents | workflow.py | 重构 |
| agents | rules.py | 重构 + 删除死代码 |
| scheduler | scheduler.py | 重构 |
| memory | store.py | 重构 |
| memory | forget.py | 重构 |
| memory | retrieval.py | 重构 |
| memory | lifecycle.py | 重构 |
| memory | memory.py | 接口调整 |
| tools | executor.py | 修复 |
| api | main.py | 修复 |
| voice | pipeline.py | 修复 |
| config | — | 不动 |
