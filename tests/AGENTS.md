# 测试

测试目录按 `app/` 模块结构镜像组织。

## 运行命令

```
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm      # 需要真实LLM
uv run pytest tests/ -v --test-embedding # 需要真实embedding
uv run pytest tests/ -v --run-integration # 需要完整服务
```

pytest.ini：asyncio_mode=auto, asyncio_default_fixture_loop_scope=function, timeout=30, addopts=-n auto, testpaths=tests, filterwarnings=ignore:builtin type Swig:DeprecationWarning。

`tests/conftest.py` 提供：
- `pytest_configure` 注册 `integration` / `llm` / `embedding` 三个标记
- `pytest_addoption` 注册 `--run-integration` / `--test-llm` / `--test-embedding` 选项
- `pytest_collection_modifyitems` 根据选项跳过带标记测试（未提供选项时跳过标有对应标记的测试）
- `llm_provider` 和 `embedding` 两个会话级 fixture

## 目录结构

```
tests/
├── conftest.py          # pytest 配置、marker 注册、会话级 fixture
├── _helpers.py          # 通用测试辅助
├── fixtures.py          # 通用 fixture 和清理函数
├── agents/              # → app/agents/
│   ├── test_conversation.py       # 会话管理
│   ├── test_outputs.py            # 输出格式化
│   ├── test_pending.py            # 待处理事件队列
│   ├── test_probabilistic.py      # 概率推断模块
│   ├── test_rules.py              # 规则引擎合并策略
│   ├── test_shortcuts.py          # 快捷键路由
│   ├── test_llm_json_validation.py # LLM JSON 输出验证
│   ├── test_sse_stream.py         # SSE 流式测试
│   └── test_workflow_llm_json.py  # LLMJsonResponse.from_llm 解析测试
├── api/                  # → app/api/
│   └── test_rest.py               # REST API 端点
├── memory/               # → app/memory/
│   ├── test_forgetting.py         # 遗忘曲线单元测试（确定性/概率模式、阈值、节流）
│   ├── test_retrieval_pipeline.py # 六阶段检索管道（mock FAISS + Embedding）
│   ├── test_index_recovery.py     # FAISS 降级恢复（损坏/计数不匹配/备份）
│   ├── test_memory_bank.py        # 记忆写入 → 检索 → 回放集成测试
│   ├── test_memory_module_facade.py # MemoryModule Facade 接口测试
│   ├── test_memory_store_contract.py # MemoryStore Protocol 契约
│   ├── test_multi_user.py         # 多用户隔离
│   ├── test_schemas.py            # 数据模式定义
│   ├── test_privacy.py            # 隐私过滤与脱敏
│   ├── test_cosine_similarity.py  # 余弦相似度计算
│   ├── test_embedding.py          # Embedding 语义检索集成（需真实 embedding）
│   ├── test_embedding_client.py   # Embedding API 客户端
│   └── stores/                    # MemoryBank 存储层单元测试
│       ├── test_bg_tasks.py       # 后台任务
│       ├── test_faiss_index.py    # FAISS 索引
│       ├── test_forget.py         # 遗忘逻辑
│       ├── test_lifecycle_inflight.py # 生命周期（进行中操作）
│       ├── test_llm.py            # LLM 摘要调用
│       ├── test_memory_bank_store.py # 存储层操作
│       ├── test_retrieval.py      # 检索
│       └── test_summarizer.py     # 摘要
├── models/               # → app/models/
│   ├── test_chat.py               # ChatModel 客户端缓存（_get_cached_client）
│   └── test_settings.py           # 模型配置加载
├── schemas/              # → app/schemas/
│   └── test_context_schemas.py    # 上下文数据模型验证
├── storage/              # → app/storage/
│   ├── test_jsonl_store.py        # JSONL 存储引擎
│   ├── test_storage.py            # 存储层持久化与反馈学习（模块级 pytestmark = [pytest.mark.embedding]，需 --test-embedding 运行；CI 的 `uv run pytest -v` 不带该标记，此文件被整体跳过）
│   ├── test_experiment_results.py # 实验结果反序列化（read_benchmark）
│   └── test_feedback_log.py      # 反馈日志追加与权重聚合
└── experiments/          # → experiments/
    ├── test_ablation_optimization.py # 消融实验优化逻辑
    ├── test_io.py                 # IO 工具
    ├── test_metrics.py            # 评测指标
    ├── test_personalization.py    # 个性化
    ├── test_protocol.py           # 实验协议
    ├── test_scenario_synthesizer.py # 场景合成
    ├── test_types.py              # 类型定义
    ├── test_ablation_runner.py    # 消融实验运行器测试
    └── test_report.py             # 报告生成测试
```

## CI 工作流

`.github/workflows/python.yml`。push/PR 到 main 时触发，四并行 job：

| Job | 命令 | 说明 |
|-----|------|------|
| `lint` | `uv run ruff check .` | 代码风格 |
| `format` | `uv run ruff format --check .` | 格式检查 |
| `typecheck` | `uv run ty check .` | 类型检查 |
| `test` | `uv run pytest -v` | 单测（无外部 provider） |

额外 workflow `no-suppressions.yml`：扫描 `# noqa` 和 `# ty:` 内联抑制注释，禁止绕过。注意：CI 中 type-ignore job 搜索 `# type:`（第46行），而项目实际使用 `# ty:` 作为 ty 的抑制注释格式，二者不匹配。
