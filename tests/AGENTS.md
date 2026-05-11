# tests - 测试

## 运行测试

```bash
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm           # 需要真实LLM
uv run pytest tests/ -v --test-embedding     # 需要真实embedding
uv run pytest tests/ -v --run-integration    # 需要完整服务
```

pytest.ini：`asyncio_mode=auto`, `asyncio_default_fixture_loop_scope=function`, `timeout=30`, `-n auto`, `filterwarnings` 忽略 `Swig` DeprecationWarning。

## conftest.py

- `pytest_configure` 注册 `integration` / `llm` / `embedding` 标记
- `pytest_addoption` 注册 `--run-integration` / `--test-llm` / `--test-embedding` 选项
- `pytest_collection_modifyitems` 根据选项跳过未标记测试
- `llm_provider` 和 `embedding` 两个会话级 fixture

## 测试文件分类

| 类别 | 文件 | 说明 |
|------|------|------|
| Agent | `test_rules.py`, `test_probabilistic.py`, `test_conversation.py`, `test_shortcuts.py`, `test_outputs.py`, `test_pending.py` | 规则引擎、概率推断、对话、快捷指令 |
| API | `test_graphql.py` | GraphQL 端点 |
| 数据模型 | `test_context_schemas.py`, `test_schemas.py` | Pydantic 验证 |
| 存储 | `test_storage.py`, `test_jsonl_store.py` | TOML/JSONL 持久化 |
| 模型 | `test_settings.py`, `test_chat.py`, `test_embedding.py` | 模型配置与调用 |
| 记忆 | `test_memory_bank.py`, `test_forgetting.py`, `test_retrieval_pipeline.py`, `test_index_recovery.py`, `test_multi_user.py`, `test_memory_store_contract.py`, `test_memory_module_facade.py`, `test_embedding_client.py`, `test_privacy.py`, `test_cosine_similarity.py`, `test_experiment_results.py` | MemoryBank、FAISS、检索、隐私、工具函数 |
| 记忆子模块 | `tests/stores/`（test_bg_tasks, test_faiss_index, test_forget, test_lifecycle_inflight, test_llm, test_memory_bank_store, test_retrieval, test_summarizer） | MemoryBank 各组件 |
| 实验 | `tests/experiments/`（test_cohens_kappa, test_io, test_metrics, test_personalization, test_scenario_synthesizer, test_types） | 消融实验框架 |

参见 [tests/stores/AGENTS.md](stores/AGENTS.md) 和 [tests/experiments/AGENTS.md](experiments/AGENTS.md) 详述。

## CI 工作流（.github/workflows/）

push/PR 到 main 时触发，三个并行 job：

| Job | 命令 |
|-----|------|
| `lint` | `ruff check .` + `ruff format --check .` |
| `typecheck` | `ty check .` |
| `test` | `uv run pytest -v`（无外部 provider） |

额外 `no-suppressions.yml`：扫描 `# noqa` 和 `# type:` 内联抑制注释。
