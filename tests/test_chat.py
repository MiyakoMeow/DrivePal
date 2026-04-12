"""聊天模型集成测试."""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from app.agents.state import AgentState, WorkflowStages
from app.agents.workflow import AgentWorkflow
from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode
from app.models.chat import (
    ChatModel,
    _get_provider_semaphore,
    _semaphore_cache,
)
from app.models.settings import LLMProviderConfig
from app.models.types import ProviderConfig
from tests._helpers import _mock_async_client

if TYPE_CHECKING:
    from pathlib import Path

# 替换测试中的魔法值
MAX_ACTIVE = 2  # 测试并发上限
EXPECTED_RESULTS_COUNT = 4  # 测试预期结果数量
PROVIDER_A_CONCURRENCY = 2  # Provider A 的并发数
PROVIDER_B_CONCURRENCY = 3  # Provider B 的并发数


@pytest.mark.integration
async def test_chat_drives_llm_memory_search(
    tmp_path: Path,
    llm_provider: LLMProviderConfig | None,
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
    tmp_path: Path,
    llm_provider: LLMProviderConfig | None,
) -> None:
    """验证记忆上下文被注入到代理工作流状态中."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")

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
    tmp_path: Path,
    llm_provider: LLMProviderConfig | None,
) -> None:
    """验证 run_with_stages 返回包含各阶段输出的 WorkflowStages 对象."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")

    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    workflow = AgentWorkflow(memory_module=memory)

    result, _event_id, stages = await workflow.run_with_stages(
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
    tmp_path: Path,
    llm_provider: LLMProviderConfig | None,
) -> None:
    """验证高速公路场景下规则引擎约束生效."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")

    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    workflow = AgentWorkflow(memory_module=memory)

    result, _event_id, _stages = await workflow.run_with_stages(
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
        _semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="test-model",
                    base_url="http://fake:8000/v1",
                    api_key="sk-test",
                ),
                concurrency=2,
            ),
        ]
        chat = ChatModel(providers=providers)

        active_count = 0
        max_active = 0

        async def mock_create(*_args: object, **_kwargs: object) -> MagicMock:
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            return mock_response

        with patch.object(chat, "_create_client") as mock_create_client:
            mock_client = _mock_async_client()
            mock_client.chat.completions.create = mock_create
            mock_create_client.return_value = mock_client

            tasks = [chat.generate(f"prompt{i}") for i in range(4)]
            results = await asyncio.gather(*tasks)

        assert max_active == MAX_ACTIVE
        assert len(results) == EXPECTED_RESULTS_COUNT

    async def test_different_providers_have_independent_semaphores(self) -> None:
        """验证不同 provider 的 semaphore 独立."""
        _semaphore_cache.clear()
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="model-a",
                    base_url="http://a:8000",
                    api_key="sk-a",
                ),
                concurrency=2,
            ),
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="model-b",
                    base_url="http://b:8000",
                    api_key="sk-b",
                ),
                concurrency=3,
            ),
        ]
        ChatModel(providers=providers)

        sem_a = await _get_provider_semaphore("http://a:8000", 2)
        sem_b = await _get_provider_semaphore("http://b:8000", 3)

        assert sem_a._value == PROVIDER_A_CONCURRENCY
        assert sem_b._value == PROVIDER_B_CONCURRENCY
