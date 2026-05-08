# 非记忆模块重构设计方案

## 概述

针对 DrivePal-2 中除记忆系统外的 4 个模块层（storage / agents / models / api）共 12 个问题进行系统性修复，分 4 批次实施。

---

## Batch 1: Storage — JSON Lines 迁移

### 动机

`TOMLStore` 全文件重写 + `asyncio.Lock` 仅进程内安全，交互日志类数据不适合 TOML。

### 改动

1. 新建 `app/storage/jsonl_store.py`
   - `JSONLinesStore`：追加写（O(1)），按行读取
   - 进程安全（O_APPEND 语义）
   - 接口：`append(obj)`, `read_all()`, `count()`
2. 文件替换
   - `events.toml` → `events.jsonl`
   - `feedback.toml` → `feedback.jsonl`
   - `interactions.toml` → `interactions.jsonl`
   - `experiment_results.toml` → `experiment_results.jsonl`
3. `TOMLStore` 保留，仅给 `strategies.toml`, `preferences.toml`, `scenario_presets.toml` 等 dict/小数据用
4. `init_data.py` 创建 `.jsonl` 文件（空文件），移除旧 TOML 创建逻辑
5. 不保留旧 TOML → JSONL 的向后兼容迁移

### 涉及文件

- `app/storage/jsonl_store.py`（新建）
- `app/storage/toml_store.py`（不动）
- `app/storage/init_data.py`（改）
- 所有引用 `events.toml` / `feedback.toml` 的代码（memory 层、workflow 层）

---

## Batch 2: Agents — 规则硬约束 + Workflow 重构

### 动机

规则引擎当前为 LLM prompt 软建议，安全规则可被 LLM 绕过；`AgentWorkflow` 神类职责过重。

### 改动

1. `app/agents/rules.py`：新增 `postprocess_decision()`
   - 输入：LLM 输出的 decision dict + driving_context
   - 输出：强制覆盖后的 decision
   - 规则：
     - `postpone=True` → `reminder_content` 置空，`should_remind=false`
     - `allowed_channels` 过滤非法通道
     - `only_urgent=True` → 非紧急类型（general/tip）的 `reminder_content` 置空，`should_remind=false`；紧急类型（safety/warning）正常通过
   - `apply_rules` 保持原样（仍用于 prompt）
2. `app/agents/workflow.py`：
   - `_execution_node` 在真正执行前调用 `postprocess_decision`
   - `_call_llm_json` 支持 JSON mode（有则用结构化输出，无则 fallback text parsing）
   - `_extract_content` 用 Pydantic 校验 + 兜底

### 涉及文件

- `app/agents/rules.py`
- `app/agents/workflow.py`

---

## Batch 3: Models — 死代码 + 资源管理

### 改动

1. `app/models/model_string.py`：删除 `get_model_group_providers()` 函数
   - 已确认无任何调用方
   - 保留 `resolve_model_string()`、`_load_config()` 等仍在使用的函数
2. `app/models/chat.py`：semaphore 缓存管理
   - `fixtures.py` 中 `reset_all_singletons` 新增 `_semaphore_cache.clear()`
3. `app/models/embedding.py`：后台任务简化
   - `clear_embedding_model_cache()` 中用 `asyncio.run` 同步关闭，不再创建后台 task
   - 移除 `_background_tasks`、`_finalize_background_task`

### 涉及文件

- `app/models/model_string.py`
- `app/models/chat.py`
- `app/models/embedding.py`
- `tests/fixtures.py`

---

## Batch 4: API — DRY 异常 + GQL 映射简化

### 改动

1. `app/api/resolvers/mutation.py`：DRY 异常处理
   - 提取 `_safe_memory_call(coro, context_msg)` 辅助函数
   - 统一将 OSError / RuntimeError / ValueError → GraphQLError
   - `InternalServerError` 兜底
2. `app/api/resolvers/mutation.py` + `graphql_schema.py`：pydantic 集成
   - 用 `strawberry.experimental.pydantic` 从 `DrivingContext` 自动生成 `DrivingContextGQL`
   - 消除 `_input_to_context`（用 pydantic model_validate 替代）
   - 消除 `_dict_to_gql_context`（用自动生成的 type 替代）

### 涉及文件

- `app/api/resolvers/mutation.py`
- `app/api/graphql_schema.py`

---

## 批次顺序

```
Batch 1 (storage) → Batch 3 (models) → Batch 2 (agents) → Batch 4 (api)
```

原因：storage 层是底层依赖，先改；models 层改动不依赖其他批次；agents 依赖 storage + models；api 依赖 agents 和 models。

## 不在此设计范围内

- 记忆系统（MemoryBank / MemoryModule / MemoryStore）不作架构改动，仅更新引用的文件路径（events.toml → events.jsonl 等）
- 测试基础设施不作改动（conftest / fixtures 仅在需要时微调）
- WebUI 前端不作改动
- `config.py` 模块级常量不作改动
