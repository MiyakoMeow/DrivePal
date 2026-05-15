# 测试

按 `app/` 模块结构镜像。

## 运行

```
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm        # 真实LLM
uv run pytest tests/ -v --test-embedding  # 真实embedding
uv run pytest tests/ -v --run-integration  # 完整服务
```

pytest.ini：asyncio_mode=auto, timeout=30, addopts=-n auto, filterwarnings ignore Swig DeprecationWarning。

conftest.py 注册 integration/llm/embedding 三个 marker，未提供对应选项时跳过标记者。

## 目录

```
tests/
├── conftest.py              # 配置、marker、fixture
├── _helpers.py              # 辅助
├── fixtures.py              # fixture与清理
├── agents/
│   ├── test_conversation.py
│   ├── test_outputs.py
│   ├── test_pending.py
│   ├── test_probabilistic.py
│   ├── test_rules.py
│   ├── test_shortcuts.py
│   ├── test_llm_json_validation.py
│   ├── test_sse_stream.py
│   └── test_workflow_llm_json.py
├── voice/
│   └── test_vad.py
├── scheduler/
│   └── test_scheduler.py
├── tools/
│   └── test_registry.py
├── api/
│   └── test_rest.py
├── memory/
│   ├── test_forgetting.py
│   ├── test_retrieval_pipeline.py
│   ├── test_index_recovery.py
│   ├── test_memory_bank.py
│   ├── test_memory_module_facade.py
│   ├── test_memory_store_contract.py
│   ├── test_multi_user.py
│   ├── test_schemas.py
│   ├── test_privacy.py
│   ├── test_cosine_similarity.py
│   ├── test_embedding.py         # 需 --test-embedding
│   ├── test_embedding_client.py
│   └── stores/
│       ├── test_bg_tasks.py
│       ├── test_faiss_index.py
│       ├── test_forget.py
│       ├── test_lifecycle_inflight.py
│       ├── test_llm.py
│       ├── test_memory_bank_store.py
│       ├── test_retrieval.py
│       └── test_summarizer.py
├── models/
│   ├── test_chat.py
│   └── test_settings.py
├── schemas/
│   └── test_context_schemas.py
├── storage/
│   ├── test_jsonl_store.py
│   ├── test_storage.py            # 需 --test-embedding
│   ├── test_experiment_results.py
│   └── test_feedback_log.py
└── experiments/
    ├── test_ablation_optimization.py
    ├── test_io.py
    ├── test_metrics.py
    ├── test_personalization.py
    ├── test_protocol.py
    ├── test_scenario_synthesizer.py
    ├── test_types.py
    ├── test_ablation_runner.py
    └── test_report.py
```

## CI

`.github/workflows/python.yml`。push/PR到main触发，四并行job：

| Job | 命令 |
|-----|------|
| lint | `uv run ruff check .` |
| format | `uv run ruff format --check .` |
| typecheck | `uv run ty check .` |
| test | `uv run pytest -v` |

额外 `no-suppressions.yml`：扫描禁止 `# noqa`/`# type:`/`# ty:`。
