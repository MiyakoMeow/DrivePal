# 实验正确性问题修复与优化

## 范围

修复消融实验（`experiments/ablation/`）和 VehicleMemBench 集成（`experiments/vehicle_mem_bench/`）中识别的 7 个正确性问题，同步执行代码质量、测试、文档四项优化。

## 修复

### 1. 个性化组续跑丢反馈状态（中）

**现状**：`feedback_simulator.py` 中 `_current_delta`、`_recent_feedback` 为模块级可变 dict，不持久化。实验中断后重启进程，自适应步长从 0.1 重置。

**修改**：

- `feedback_simulator.py`：新增 `export_state() -> dict` 和 `restore_state(state: dict) -> None` 两函数
- `_io.py`：`append_checkpoint` 增加可选 `extra: dict | None` 参数，写入 JSONL 行时作为顶级字段合并
- `_io.py`：`load_checkpoint` 返回值改为 `tuple[set, list[VariantResult], dict | None]`（第三个元素为最后一条 extra 状态，None 表示无）
- `personalization_group.py`：每轮结束后 `append_checkpoint` 时附带 `export_state()` 输出；续跑时在开始前检查 checkpoint 最后一条 `extra` 并调用 `restore_state()`

**影响文件**：`feedback_simulator.py`、`_io.py`、`personalization_group.py`

### 2. pers_stratum 依赖 LLM 输出（低）

**现状**：`pers_stratum(s)` 用 `s.expected_task_type`，该字段优先取 LLM 输出 `data.get("expected_task_type")`，回退 `combo["task_type"]`。LLM 返回非标准值导致分层不稳定。

**修改**：`pers_stratum` 改为 `s.synthesis_dims.get("task_type", "unknown")`。直接取合成维度（确定值），与 `safety_stratum`/`arch_stratum` 风格一致。

**影响文件**：`personalization_group.py`

### 3. has_visual_content 冗余偏好（极低）

**现状**：函数优先从 `stages["decision"]` 读，fallback 到 `decision`。但 `execution_agent.py:74` 同步了两者，故恒等同。

**修改**：删除 stages 参数及相关逻辑。简化签名为 `has_visual_content(decision: dict) -> bool`。`preference_metrics.py` 中调用方去除 stages 参数。

**影响文件**：`feedback_simulator.py`、`preference_metrics.py`

### 4. VehicleMemBench memory_strength 硬编码（中）

**现状**：`DrivePalMemClient._async_add` 所有 entry 使用 `memory_strength=3`，无重要性区分。

**修改**：

- `_async_add` 增加 `strength: int = 3` 参数
- `run_add` 的 `processor` 闭包中，检查 content 是否含显式偏好关键词（"设置"、"改成"、"调"、"偏好"、"喜欢"、"换成"、"切换"、"设定"），含则传 strength=5，否则 strength=3

**影响文件**：`adapter.py`

### 5. run-all benchmark_dir 硬编码（低）

**现状**：`_cmd_run_all` 内 `benchmark_dir = str(vmb_root / "benchmark" / "qa_data")` 硬编码。

**修改**：`run-all` argparse 增加 `--benchmark-dir` 参数，默认值同硬编码路径。`_cmd_run_all` 中改为 `args.benchmark_dir or str(vmb_root / ...)`。

**影响文件**：`__main__.py`

### 6. 架构组上下文对齐（低）

**现状**：`_run_single_llm` 的 memory_context 构建格式与 `ContextAgent` 可能不一致。

**修改**：在 `_run_single_llm` 中，memory_context 的格式化与 `app/agents/context_agent.py` 中 `_format_memory_for_context` 对齐。追加 `current_datetime` 字段到 user_msg_data（已通过 SINGLE_LLM_SYSTEM_PROMPT 注入，此处确保 JSON 中也含）。

**影响文件**：`ablation_runner.py`

### 7. 分层函数无类型防御（极低）

**现状**：`safety_stratum` 和 `arch_stratum` 中 `float(d["fatigue_level"])` 对非数字值抛异常。

**修改**：加 try/except ValueError TypeError，回退默认值 0.5。

**影响文件**：`safety_group.py`、`architecture_group.py`

## 优化

### 代码质量

- 问题修复后 `feedback_simulator.py` 的 `_current_delta`、`_recent_feedback` 可由纯模块级 dict 改为通过 `export_state`/`restore_state` 管理的可序列化状态（保持模块级以兼容现有串行调用，但持久化路径清晰）
- `has_visual_content` 签名简化，移除未使用的 stages 参数
- `personalization_group.py` 中 `run_personalization_group` 增加 checkpoint 状态的恢复分支

### 测试覆盖

新增测试文件 `tests/experiments/test_ablation_correctness.py`：

- `test_pers_stratum_uses_synthesis_dims`：验证 `pers_stratum` 使用合成维度
- `test_safety_stratum_handles_non_float_fatigue`：验证 `safety_stratum` 对非数字 fatigue 回退
- `test_export_restore_feedback_state`：验证 `export_state`/`restore_state` 往返
- `test_has_visual_content_simplified`：验证简化后的 `has_visual_content`

### 文档同步

- `experiments/ablation/AGENTS.md`：个性化组增加"Checkpoint 续跑支持反馈状态恢复"说明
- `experiments/vehicle_mem_bench/AGENTS.md`：`run-all` 用法增加 `--benchmark-dir` 参数说明

## 不予修改

- 问题 3（has_visual_content 冗余偏好）：简化签名后已消除冗余
- 问题 6 中 conversation_history 对齐：合成场景无历史对话，注入空列表等于无操作。对齐 memory_context 格式即可
- 问题 6 中策略权重对齐：架构组 Full 变体通过 AgentWorkflow 读取策略权重，SingleLLM 无策略概念——此为架构差异本身，不应消除

## 验证计划

1. `uv run ruff check --fix && uv run ruff format && uv run ty check`
2. `uv run pytest tests/experiments/ -v`
3. `uv run pytest tests/ -q`（确保全量测试无回归）
