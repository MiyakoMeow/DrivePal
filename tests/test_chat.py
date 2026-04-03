"""聊天模型集成测试."""

import pytest
from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode
from app.models.chat import ChatModel
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.settings import LLMProviderConfig
    from pathlib import Path
    from app.agents.state import AgentState


@pytest.mark.integration
async def test_chat_drives_llm_memory_search(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证聊天驱动的 LLM 记忆搜索能检索到相关事件."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    await memory.write(MemoryEvent(content="明天下午三点项目会议", type="meeting"))
    results = await memory.search("有什么会议安排", mode=MemoryMode.MEMORY_BANK)
    assert len(results) > 0
    assert "会议" in results[0].event["content"]


@pytest.mark.integration
async def test_chat_feeds_workflow_context(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证记忆上下文被注入到代理工作流状态中."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    from app.agents.workflow import AgentWorkflow

    memory = MemoryModule(tmp_path, chat_model=ChatModel(providers=[llm_provider]))
    await memory.write(MemoryEvent(content="下午三点开会", type="meeting"))
    workflow = AgentWorkflow(memory_module=memory)

    state: AgentState = {
        "messages": [{"role": "user", "content": "查一下会议"}],
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
        "driving_context": None,
        "stages": None,
    }
    result = await workflow._context_node(state)
    assert "related_events" in result["context"]


@pytest.mark.integration
async def test_run_with_stages_returns_stages_object(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证 run_with_stages 返回包含各阶段输出的 WorkflowStages 对象."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    from app.agents.state import WorkflowStages
    from app.agents.workflow import AgentWorkflow

    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    workflow = AgentWorkflow(memory_module=memory)

    result, event_id, stages = await workflow.run_with_stages(
        "明天上午9点有个会议",
        driving_context={
            "scenario": "parked",
            "driver": {"fatigue_level": 0.2, "workload": "normal"},
        },
    )
    assert result is not None
    assert isinstance(stages, WorkflowStages)
    assert stages.context is not None
    assert stages.task is not None
    assert stages.decision is not None
    assert stages.execution is not None


@pytest.mark.integration
async def test_run_with_stages_highway_scenario(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证高速公路场景下规则引擎约束生效."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    from app.agents.workflow import AgentWorkflow

    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    workflow = AgentWorkflow(memory_module=memory)

    result, event_id, stages = await workflow.run_with_stages(
        "提醒我回电话",
        driving_context={
            "scenario": "highway",
            "driver": {"fatigue_level": 0.1, "workload": "normal"},
            "traffic": {"congestion_level": "smooth"},
        },
    )
    assert "提醒已发送" in result or "提醒已延后" in result


class TestProviderConcurrency:
    """Provider 级别并发控制测试."""

    async def test_concurrent_requests_respected(self) -> None:
        """验证并发请求受 provider semaphore 限制."""
        import asyncio
        from unittest.mock import MagicMock, patch

        from app.models.chat import ChatModel, _provider_semaphore_cache
        from app.models.settings import LLMProviderConfig, ProviderConfig

        _provider_semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="test-model",
                    base_url="http://fake:8000/v1",
                    api_key="sk-test",
                ),
                concurrency=2,
            )
        ]
        chat = ChatModel(providers=providers)

        active_count = 0
        max_active = 0

        async def mock_create(*args, **kwargs):
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            return mock_response

        with patch.object(chat, "_create_async_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create = mock_create
            mock_create_client.return_value = mock_client

            tasks = [chat.generate(f"prompt{i}") for i in range(4)]
            results = await asyncio.gather(*tasks)

        assert max_active == 2
        assert len(results) == 4

    async def test_different_providers_have_independent_semaphores(self) -> None:
        """验证不同 provider 的 semaphore 独立."""
        from app.models.chat import (
            ChatModel,
            _provider_semaphore_cache,
            _get_provider_semaphore,
        )
        from app.models.settings import LLMProviderConfig, ProviderConfig

        _provider_semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="model-a", base_url="http://a:8000", api_key="sk-a"
                ),
                concurrency=2,
            ),
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="model-b", base_url="http://b:8000", api_key="sk-b"
                ),
                concurrency=3,
            ),
        ]
        chat = ChatModel(providers=providers)

        sem_a = await _get_provider_semaphore("model-a", 2)
        sem_b = await _get_provider_semaphore("model-b", 3)

        assert sem_a._value == 2
        assert sem_b._value == 3
