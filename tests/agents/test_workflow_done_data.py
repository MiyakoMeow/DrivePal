"""测试 _build_done_data 方法（含 rules modifications 附加逻辑）。"""

from __future__ import annotations

from typing import cast

from app.agents.state import AgentState, WorkflowStages
from app.agents.workflow import AgentWorkflow


def _mk_state(**kw: object) -> AgentState:
    """构造 AgentState，dict 构造避免 TypedDict 全字段约束。"""
    return cast("AgentState", kw)


def test_build_done_data_no_modifications() -> None:
    """无规则引擎修改时 done_data 不含 modifications 字段。"""
    stages = WorkflowStages()
    state = _mk_state(
        original_query="",
        context={},
        task=None,
        decision=None,
        result="已发送提醒",
        event_id="evt_001",
        driving_context=None,
        stages=stages,
        output_content="已发送提醒",
    )
    done = AgentWorkflow._build_done_data(state, "session_1")
    assert done["status"] == "delivered"
    assert "modifications" not in done


def test_build_done_data_with_modifications() -> None:
    """含规则引擎修改时 done_data 含 modifications 列表。"""
    stages = WorkflowStages()
    stages.execution = {"modifications": ["通道: visual→audio", "频率: 30min"]}
    state = _mk_state(
        original_query="",
        context={},
        task=None,
        decision=None,
        result="已发送提醒",
        event_id="evt_002",
        driving_context=None,
        stages=stages,
        output_content="已发送提醒",
    )
    done = AgentWorkflow._build_done_data(state, "session_1")
    assert "modifications" in done
    assert len(done["modifications"]) == 2
    assert done["modifications"][0] == "通道: visual→audio"


def test_build_done_data_pending_with_modifications() -> None:
    """pending 状态时 modifications 正常附加。"""
    stages = WorkflowStages()
    stages.execution = {"modifications": ["通道: visual→audio"]}
    state = _mk_state(
        original_query="",
        context={},
        task=None,
        decision=None,
        result=None,
        event_id="evt_003",
        driving_context=None,
        stages=stages,
        pending_reminder_id="pr_001",
    )
    done = AgentWorkflow._build_done_data(state, "session_1")
    assert done["status"] == "pending"
    assert done["pending_reminder_id"] == "pr_001"
    assert "modifications" in done
    assert len(done["modifications"]) == 1


def test_build_done_data_stages_none() -> None:
    """stages 为 None 时 modifications 安全处理。"""
    state = _mk_state(
        original_query="",
        context={},
        task=None,
        decision=None,
        result="已发送提醒",
        event_id="evt_004",
        driving_context=None,
        stages=None,
        output_content="已发送提醒",
    )
    done = AgentWorkflow._build_done_data(state, "session_1")
    assert "modifications" not in done
