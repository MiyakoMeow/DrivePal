# 测试

## 运行命令

```
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm      # 需要真实LLM
uv run pytest tests/ -v --test-embedding # 需要真实embedding
uv run pytest tests/ -v --run-integration # 需要完整服务
```

pytest.ini：asyncio_mode=auto, asyncio_default_fixture_loop_scope=function, timeout=30, -n auto, testpaths=tests, filterwarnings=ignore:builtin type Swig:DeprecationWarning。

`tests/conftest.py` 提供：
- `pytest_configure` 注册 `integration` / `llm` / `embedding` 三个标记
- `pytest_addoption` 注册 `--run-integration` / `--test-llm` / `--test-embedding` 选项
- `pytest_collection_modifyitems` 根据选项跳过带标记测试（未提供选项时跳过标有对应标记的测试）
- `llm_provider` 和 `embedding` 两个会话级 fixture

## 子目录

| 目录 | 测什么 |
|------|--------|
| `tests/stores/` | MemoryBank 存储层单元测试（FAISS、遗忘、后台任务、检索、摘要、生命周期、LLM 摘要调用、存储层操作） |
| `tests/experiments/` | 消融实验工具（场景合成、个性化、指标、IO、类型） |

## 关键测试文件

| 文件 | 测什么 |
|------|--------|
| test_rules.py | 规则引擎合并策略 |
| test_context_schemas.py | 数据模型验证 |
| test_graphql.py | GraphQL端点 |
| test_memory_bank.py | 记忆写入 → 检索 → 回放集成测试 |
| test_forgetting.py | 遗忘曲线单元测试（确定性/概率模式、阈值、节流） |
| test_retrieval_pipeline.py | 四阶段检索管道（mock FAISS + Embedding） |
| test_index_recovery.py | FAISS 降级恢复（损坏/计数不匹配/备份） |
| test_multi_user.py | 多用户隔离 |
| test_memory_store_contract.py | MemoryStore Protocol 契约 |
| test_memory_module_facade.py | MemoryModule Facade 接口测试 |
| test_settings.py | 模型配置加载 |
| test_storage.py | 存储层持久化与反馈学习 |
| test_schemas.py | 数据模式定义 |
| test_privacy.py | 隐私过滤与脱敏 |
| test_probabilistic.py | 概率推断模块 |
| test_chat.py | ChatModel 客户端缓存（_get_cached_client） |
| test_conversation.py | 会话管理 |
| test_embedding.py | Embedding 封装 |
| test_embedding_client.py | Embedding API 客户端 |
| test_jsonl_store.py | JSONL 存储引擎 |
| test_outputs.py | 输出格式化 |
| test_pending.py | 待处理事件队列 |
| test_shortcuts.py | 快捷键路由 |
| test_cosine_similarity.py | 余弦相似度计算 |
| test_ablation_optimization.py | 消融实验优化逻辑 |
| test_experiment_results.py | 实验结果反序列化（read_benchmark） |

## CI 工作流

`.github/workflows/python.yml`。push/PR 到 main 时触发，三个并行 job：

| Job | 命令 | 说明 |
|-----|------|------|
| `lint` | `uv run ruff check .` + `uv run ruff format --check .` | 代码风格 + 格式 |
| `typecheck` | `uv run ty check .` | 类型检查 |
| `test` | `uv run pytest -v` | 单测（无外部 provider） |

额外 workflow `no-suppressions.yml`：扫描 `# noqa` 和 `# type:` 内联抑制注释，禁止绕过。
