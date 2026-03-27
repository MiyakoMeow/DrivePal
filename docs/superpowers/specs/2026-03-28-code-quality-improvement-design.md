# 代码质量系统性改进设计

日期：2026-03-28

## 背景

对 thesis-cockpit-memo 项目进行全面的代码质量审计，发现约 70 个问题（10 高严重度、24 中严重度、36+ 低严重度）。本设计采用分阶段渐进式修复方案，确保每步独立可交付、可验证。

## 方案选择

| 方案 | 描述 | 优缺点 |
|------|------|--------|
| **A（选定）** | 4 阶段渐进修复 | 风险可控，每步可验证，不破坏现有功能 |
| B | 重构 3 个核心模块 | 一次性解决但改动面大，回归风险高 |
| C | 只修高严重度 | 最快但技术债持续积累 |

---

## P0：紧急修复

### P0.1 `hash()` → `hashlib`

**文件**：`app/agents/workflow.py:199-201`

**问题**：`str(hash(str(decision)))` 在 Python 3.3+ 中因 hash seed 随机化而不确定。

**方案**：替换为 `hashlib.md5(str(decision).encode()).hexdigest()[:8]`。

### P0.2 XSS 修复

**文件**：`webui/index.html:92-93`

**问题**：`innerHTML` 直接插入用户数据。

**方案**：使用 `textContent` 赋值 + `createElement`，或添加 HTML 转义函数。

### P0.3 死代码清理

- `app/storage/json_store.py:8-11`：删除空 `sys.platform` 分支及 `import sys`
- `app/storage/json_store.py:49-51`：删除冗余 `save()` 方法
- `app/experiment/runner.py:355-367`：删除未使用的 `_extract_task_indicators` 和 `_get_type_patterns`
- `app/agents/workflow.py:43-46`：合并重复的 `elif/else` 分支
- `app/agents/workflow.py:48`：删除冗余 `self.memory = self.memory_module` 别名

### P0.4 异常不再吞没

**文件**：`app/memory/memory.py:97`

**方案**：`except Exception:` → `except Exception as e:` + `logger.warning("LLM search failed: %s", e, exc_info=True)`。

### P0.5 WebUI 加 `memorybank` 选项

**文件**：`webui/index.html`

在 `<select>` 中添加 `<option value="memorybank">MemoryBank</option>`。

### P0.6 导入副作用消除

- `app/__init__.py`：移除 `init_storage()` 调用，改为延迟初始化
- `app/api/main.py:19-23`：将模块级 LLM 实例化改为请求级惰性初始化（FastAPI `Depends`）

---

## P1：架构整理

### P1.1 提取 `_llm_json_call` 公共方法

**文件**：`app/agents/workflow.py`

`_context_node`、`_task_node`、`_strategy_node` 共享模式：构建 prompt → 调 LLM → 解析 JSON → attach raw → append messages。

提取为：

```python
def _llm_json_call(self, state: AgentState, system_key: str, user_prompt: str, state_key: str) -> dict
```

每个 node 方法缩减为：构建 prompt 字符串 → 调用 `_llm_json_call` → 设置 state 字段。

### P1.2 合并 `_cosine_similarity`

**文件**：`app/memory/memory.py:137-148` + `app/memory/memory_bank.py:410-416`

提取到 `app/memory/utils.py`，两处改为引用。

### P1.3 参数化 provider 构建

**文件**：`app/models/settings.py:110-129`

`_build_openai_env_provider` 和 `_build_deepseek_env_provider` 合并为 `_build_env_provider(env_prefix: str)`。

### P1.4 路由集中注册

将 `main.py` 中的 `@app.get("/")` 移入 `app/api/main.py`，使用 `APIRouter` 管理所有路由。`main.py` 仅保留 `uvicorn.run`。

### P1.5 `NEGATIVE_PATTERNS` 修复

**文件**：`app/experiment/runner.py:111-126`

移除单字"不"，仅保留明确的否定词组（"不是"、"不要"、"不需要"、"别"、"不用"等）。

### P1.6 JSON 提取正则修复

**文件**：`app/memory/memory.py:92`

将贪心 `r"\{.*\}"` 改为非贪心 `r"\{.*?\}"`，或使用 `json.JSONDecoder().raw_decode`。

---

## P2：性能优化

### P2.1 嵌入检索批处理

**文件**：`app/memory/memory.py:102-117`

将逐事件编码改为批量编码：

```python
all_embeddings = self.embedding_model.batch_encode(event_contents)
for event, emb in zip(events, all_embeddings):
    sim = self._cosine_similarity(query_emb, emb)
```

### P2.2 MemoryBank 内部缓存 & 减少 I/O

- `_maybe_summarize` 不再每次全量读 events 计数，改为维护 `date_group → count` 的内存缓存
- `_persist_interaction` 接受已加载的 interactions dict 作为参数
- `_update_overall_summary` 接受 summaries dict 作为参数

### P2.3 JSONStore 原子写入 + 文件锁

- 使用 `filelock` 库在 `append()`/`update()` 操作期间加锁
- 写入时先写临时文件再 `os.rename`，保证原子性
- `read()` 加共享锁，`write()`/`append()`/`update()` 加排他锁

### P2.4 `_strengthen_*` 优化

合并三个 `_strengthen_events`/`_strengthen_interactions`/`_strengthen_summaries` 为统一的 `_strengthen_memory(search_results)`，在一次 read + 一次 write 中完成。

---

## P3：质量提升

### P3.1 补充缺失测试

- `MemoryModule._search_by_llm()` — mock LLM 验证 JSON 提取和异常处理
- `MemoryModule._search_by_embeddings()` — mock embedding 验证批处理
- `AgentWorkflow._task_node()` / `_strategy_node()` / `_execution_node()` — mock LLM 验证状态流转
- `ExperimentRunner.run_comparison()` — 集成测试
- API 错误路径：无效 `memory_mode`、缺失字段、边界 `limit` 值

### P3.2 `memory_mode` API 校验

使用 Pydantic `Literal` 类型：

```python
class QueryRequest(BaseModel):
    query: str
    memory_mode: Literal["keyword", "llm_only", "embeddings", "memorybank"] = "keyword"
```

### P3.3 类型一致性

- `state.py` 中 `task`/`decision` 类型改为 `dict`（非 `Optional[dict]`）
- 清理 Python 3.13 不需要的 `typing` 导入

### P3.4 清理 stale docs

删除或更新 `docs/superpowers/plans/` 中引用不存在文件的 plan。

### P3.5 `conftest.py` LLM 可用性检测增强

`is_llm_available()` 同时检查 `OPENAI_MODEL` 和 `DEEPSEEK_MODEL`，或检测 `settings.py` 的 provider 配置。

---

## 未解决问题

- 是否引入 `filelock` 作为新依赖（P2.3），还是用标准库 `fcntl.flock`（仅限 Unix）？
- P2.3 的文件锁粒度：按文件锁还是按数据目录全局锁？
