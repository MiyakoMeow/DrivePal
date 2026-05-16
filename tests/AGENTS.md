# 测试

按 `app/` 模块结构镜像。

## 运行

```
uv run pytest tests/ -v
uv run pytest tests/ -v --test-llm        # 真实LLM
uv run pytest tests/ -v --test-embedding  # 真实embedding
uv run pytest tests/ -v --run-integration  # 完整服务
```

pytest.ini：testpaths=tests, asyncio_mode=auto, asyncio_default_fixture_loop_scope=function, timeout=30, addopts=-n auto, filterwarnings ignore:builtin type Swig:DeprecationWarning + ignore::DeprecationWarning:webrtcvad。

conftest.py 注册 integration/llm/embedding 三个 marker，未提供对应选项时跳过标记者。

## 目录

```mermaid
flowchart RL
    CF["conftest.py"]
    HP["_helpers.py"]
    FX["fixtures.py"]
    subgraph Agents["tests/agents/"]
        AG1["test_conversation.py"]
        AG2["test_outputs.py"]
        AG3["test_pending.py"]
        AG4["test_probabilistic.py"]
        AG5["test_rules.py"]
        AG6["test_shortcuts.py"]
        AG7["test_llm_json_validation.py"]
        AG8["test_sse_stream.py"]
        AG9["test_workflow_llm_json.py"]
        AG10["test_workflow_proactive.py"]
        AG11["test_workflow_tool.py"]
    end
    subgraph Voice["tests/voice/"]
        VO["test_vad.py"]
        VO2["test_pipeline.py"]
        VO3["test_cli.py"]
        VO4["test_server.py"]
        VO5["test_service.py"]
    end
    subgraph Sched["tests/scheduler/"]
        SC["test_scheduler.py"]
        SC2["test_tick.py"]
    end
    subgraph Tools["tests/tools/"]
        TL["test_registry.py"]
        TL2["test_executor.py"]
    end
    subgraph API["tests/api/"]
        A01["test_rest.py"]
        A02["test_v1_feedback.py"]
        A03["test_v1_ws.py"]
        A04["test_v1_reminders.py"]
        A05["test_middleware.py"]
        A06["test_v1_presets.py"]
        A07["test_v1_query.py"]
        A08["test_ws_manager.py"]
        A09["test_v1_sessions.py"]
        A10["test_v1_data.py"]
        A11["test_voice_api.py"]
    end
    subgraph Mem["tests/memory/"]
        M1["test_forgetting.py"]
        M2["test_retrieval_pipeline.py"]
        M3["test_index_recovery.py"]
        M4["test_memory_bank.py"]
        M5["test_memory_module_facade.py"]
        M6["test_memory_store_contract.py"]
        M7["test_multi_user.py"]
        M8["test_schemas.py"]
        M9["test_privacy.py"]
        M10["test_cosine_similarity.py"]
        M11["test_embedding.py"]
        M12["test_embedding_client.py"]
        subgraph Stores["memory/stores/"]
            S1["test_bg_tasks.py"]
            S2["test_faiss_index.py"]
            S3["test_forget.py"]
            S4["test_lifecycle_inflight.py"]
            S5["test_llm.py"]
            S6["test_memory_bank_store.py"]
            S7["test_retrieval.py"]
            S8["test_summarizer.py"]
        end
    end
    subgraph Models["tests/models/"]
        MD1["test_chat.py"]
        MD2["test_settings.py"]
    end
    subgraph Schemas["tests/schemas/"]
        SH["test_context_schemas.py"]
    end
    subgraph Storage["tests/storage/"]
        ST1["test_jsonl_store.py"]
        ST2["test_storage.py"]
        ST3["test_experiment_results.py"]
        ST4["test_feedback_log.py"]
    end
    subgraph Exp["tests/experiments/"]
        E1["test_ablation_optimization.py"]
        E2["test_io.py"]
        E3["test_metrics.py"]
        E4["test_personalization.py"]
        E5["test_protocol.py"]
        E6["test_scenario_synthesizer.py"]
        E7["test_types.py"]
        E8["test_ablation_runner.py"]
        E9["test_report.py"]
        E10["test_architecture_group.py"]
    end
```

## CI

`.github/workflows/python.yml`。push/PR到main触发，四并行job：

| Job | 命令 |
|-----|------|
| lint | `uv run ruff check .` |
| format | `uv run ruff format --check .` |
| typecheck | `uv run ty check .` |
| test | `uv run pytest -v` |

额外 `no-suppressions.yml`：3 个独立 job（noqa / type-ignore / ty-ignore），各自扫描一种注释类型。
