"""Agent工作流编排模块."""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from app.agents.state import AgentState
from app.agents.prompts import SYSTEM_PROMPTS
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.storage.json_store import JSONStore
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """多Agent协作工作流."""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_mode: MemoryMode = MemoryMode.MEMORY_BANK,
        memory_module: Optional[MemoryModule] = None,
    ) -> None:
        """初始化工作流实例."""
        self.data_dir = data_dir
        self.memory_mode = memory_mode

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            from app.models.settings import get_chat_model

            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self.memory_module.set_default_mode(memory_mode)

        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """构建LangGraph工作流."""
        workflow = StateGraph(cast(Any, AgentState))

        workflow.add_node("context_agent", self._context_node)
        workflow.add_node("task_agent", self._task_node)
        workflow.add_node("strategy_agent", self._strategy_node)
        workflow.add_node("execution_agent", self._execution_node)

        workflow.set_entry_point("context_agent")
        workflow.add_edge("context_agent", "task_agent")
        workflow.add_edge("task_agent", "strategy_agent")
        workflow.add_edge("strategy_agent", "execution_agent")
        workflow.add_edge("execution_agent", END)

        return workflow.compile()

    def _call_llm_json(self, user_prompt: str) -> dict:
        """构建 prompt、调 LLM 并解析 JSON 返回 dict."""
        if not self.memory_module.chat_model:
            raise RuntimeError("ChatModel not available")
        result = self.memory_module.chat_model.generate(user_prompt)
        cleaned = re.sub(r"^```(?:json)?\s*", "", result.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                parsed = {"raw": result}
        except json.JSONDecodeError:
            parsed = {"raw": result}
        parsed["raw"] = result
        return parsed

    def _context_node(self, state: AgentState) -> dict:
        """Context Agent节点."""
        messages = state.get("messages", [])
        if not messages:
            user_input = ""
        else:
            user_input = str(messages[-1].content)

        try:
            related_events = (
                self.memory_module.search(user_input, mode=self.memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            related_events = []

        try:
            if related_events:
                relevant_memories = [e.to_public() for e in related_events]
            else:
                relevant_memories = [
                    e.model_dump() for e in self.memory_module.get_history()
                ]
        except ValueError as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )
        except Exception as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )

        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SYSTEM_PROMPTS["context"].format(
            current_datetime=current_datetime
        )

        prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

        context = self._call_llm_json(prompt)
        context["related_events"] = relevant_memories
        context["relevant_memories"] = relevant_memories

        return {
            "context": context,
            "messages": state["messages"]
            + [HumanMessage(content=f"Context: {json.dumps(context)}")],
        }

    def _task_node(self, state: AgentState) -> dict:
        """Task Agent节点."""
        messages = state.get("messages", [])
        user_input = messages[-1].content if messages else ""
        context = state.get("context", {})

        prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象. """

        task = self._call_llm_json(prompt)
        return {
            "task": task,
            "messages": state["messages"]
            + [HumanMessage(content=f"Task: {json.dumps(task)}")],
        }

    def _strategy_node(self, state: AgentState) -> dict:
        """Strategy Agent节点."""
        context = state.get("context", {})
        task = state.get("task", {})

        strategies = JSONStore(self.data_dir, Path("strategies.json"), dict).read()

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}

请输出JSON格式的决策结果. """

        decision = self._call_llm_json(prompt)
        return {
            "decision": decision,
            "messages": state["messages"]
            + [HumanMessage(content=f"Decision: {json.dumps(decision)}")],
        }

    def _execution_node(self, state: AgentState) -> dict:
        """执行提醒动作的Agent节点."""
        decision = state.get("decision") or {}
        messages = state.get("messages", [])
        user_input = str(messages[0].content) if messages else ""

        remind_content = decision.get("reminder_content") or decision.get(
            "remind_content"
        )
        if isinstance(remind_content, dict):
            content = remind_content.get("text") or remind_content.get(
                "content", "无提醒内容"
            )
        elif isinstance(remind_content, str):
            content = remind_content
        else:
            content = decision.get("content") or "无提醒内容"
        event_id = self.memory_module.write_interaction(user_input, content)
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"

        result = f"提醒已发送: {content}"
        return {
            "result": result,
            "event_id": event_id,
            "messages": state["messages"] + [HumanMessage(content=result)],
        }

    def run(self, user_input: str) -> tuple[str, Optional[str]]:
        """运行完整工作流并返回结果和事件ID."""
        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "context": {},
            "task": {},
            "decision": {},
            "memory_mode": self.memory_mode,
            "result": None,
            "event_id": None,
        }

        final_state = self.graph.invoke(initial_state)
        result = final_state.get("result") or "处理完成"
        event_id = final_state.get("event_id")
        return result, event_id


def create_workflow(
    data_dir: Path = Path("data"), memory_mode: str = "memory_bank"
) -> AgentWorkflow:
    """创建工作流实例."""
    return AgentWorkflow(data_dir, MemoryMode(memory_mode))
