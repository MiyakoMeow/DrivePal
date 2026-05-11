# tests - 测试

## 运行测试

```bash
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm           # 需要真实LLM
uv run pytest tests/ -v --test-embedding     # 需要真实embedding
uv run pytest tests/ -v --run-integration    # 需要完整服务
```

pytest.ini：`asyncio_mode=auto`, `asyncio_default_fixture_loop_scope=function`, `timeout=30`, `-n auto`。

## conftest.py

- `pytest_configure` 注册 `integration` / `llm` / `embedding` 标记
- `pytest_addoption` 注册 `--run-integration` / `--test-llm` / `--test-embedding` 选项
- `pytest_collection_modifyitems` 根据选项跳过未标记测试
- `llm_provider` 和 `embedding` 两个会话级 fixture

## 关键测试文件

| 文件 | 测什么 |
|------|--------|
| test_rules.py | 规则引擎合并策略 |
| test_context_schemas.py | 数据模型验证 |
| test_graphql.py | GraphQL 端点 |
| test_memory_bank.py | 遗忘曲线、摘要、交互聚合 |
| test_forgetting.py | 遗忘曲线单元测试 |
| test_retrieval_pipeline.py | 四阶段检索管道（mock FAISS + Embedding） |
| test_index_recovery.py | FAISS 降级恢复 |
| test_multi_user.py | 多用户隔离 |
| test_memory_store_contract.py | MemoryStore Protocol 契约 |
| test_memory_module_facade.py | Facade 工厂注册 |
| test_settings.py | 模型配置加载 |
| test_storage.py | TOMLStore 持久化 |

## CI 工作流（.github/workflows/）

push/PR 到 main 时触发，三个并行 job：

| Job | 命令 |
|-----|------|
| `lint` | `ruff check .` + `ruff format --check .` |
| `typecheck` | `ty check .` |
| `test` | `pytest -v`（无外部 provider） |

额外 `no-suppressions.yml`：扫描 `# noqa` 和 `# type:` 内联抑制注释。
