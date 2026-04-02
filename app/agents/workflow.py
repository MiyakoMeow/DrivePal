"""Agent工作流编排模块."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.rules import apply_rules, format_constraints
from app.agents.state import AgentState, WorkflowStages
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore


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
        self._memory_mode = memory_mode

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            from app.models.settings import get_chat_model

            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self._nodes = [
            self._context_node,
            self._task_node,
            self._strategy_node,
            self._execution_node,
        ]
        self._strategies_store = TOMLStore(data_dir, Path("strategies.toml"), dict)

    async def _call_llm_json(self, user_prompt: str) -> dict:
        if not self.memory_module.chat_model:
            raise RuntimeError("ChatModel not available")
        result = await self.memory_module.chat_model.generate(user_prompt)
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

    async def _context_node(self, state: AgentState) -> dict:
        messages = state.get("messages", [])
        user_input = "" if not messages else str(messages[-1].get("content", ""))
        stages = state.get("stages")

        try:
            related_events = (
                await self.memory_module.search(user_input, mode=self._memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            related_events = []

        try:
            if related_events:
                relevant_memories = [e.to_public() for e in related_events]
            else:
                relevant_memories = [
                    e.model_dump()
                    for e in await self.memory_module.get_history(
                        mode=self._memory_mode
                    )
                ]
        except Exception as e:
            logger.warning("Memory get_history failed: %s", e)
            relevant_memories = (
                [e.to_public() for e in related_events] if related_events else []
            )

        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        driving_context = state.get("driving_context")

        if driving_context:
            context = dict(driving_context)
            context["current_datetime"] = current_datetime
            context["related_events"] = relevant_memories
            context["relevant_memories"] = relevant_memories
        else:
            system_prompt = SYSTEM_PROMPTS["context"].format(
                current_datetime=current_datetime
            )

            prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

            context = await self._call_llm_json(prompt)
            context["related_events"] = relevant_memories
            context["relevant_memories"] = relevant_memories

        if stages is not None:
            stages["context"] = context

        return {
            "context": context,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Context: {json.dumps(context)}"}],
        }

    async def _task_node(self, state: AgentState) -> dict:
        messages = state.get("messages", [])
        user_input = messages[-1].get("content", "") if messages else ""
        context = state.get("context", {})
        stages = state.get("stages")

        prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象. """

        task = await self._call_llm_json(prompt)
        if stages is not None:
            stages["task"] = task
        return {
            "task": task,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Task: {json.dumps(task)}"}],
        }

    async def _strategy_node(self, state: AgentState) -> dict:
        context = state.get("context", {})
        task = state.get("task") or {}
        stages = state.get("stages")

        strategies = await self._strategies_store.read()

        constraints_block = ""
        driving_context = state.get("driving_context")
        if driving_context:
            constraints = apply_rules(driving_context)
            constraints_block = "\n\n" + format_constraints(constraints)

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}{constraints_block}

请输出JSON格式的决策结果. """

        decision = await self._call_llm_json(prompt)
        if stages is not None:
            stages["decision"] = decision
        return {
            "decision": decision,
            "messages": state["messages"]
            + [{"role": "user", "content": f"Decision: {json.dumps(decision)}"}],
        }

    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        messages = state.get("messages", [])
        user_input = str(messages[0].get("content", "")) if messages else ""
        stages = state.get("stages")

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
        event_id = await self.memory_module.write_interaction(
            user_input, content, mode=self._memory_mode
        )
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = f"unknown_{hashlib.md5(str(decision).encode()).hexdigest()[:8]}"

        result = f"提醒已发送: {content}"
        if stages is not None:
            stages["execution"] = {
                "content": content,
                "event_id": event_id,
                "result": result,
            }
        return {
            "result": result,
            "event_id": event_id,
            "messages": state["messages"] + [{"role": "user", "content": result}],
        }

    async def run_with_stages(
        self,
        user_input: str,
        driving_context: dict | None = None,
    ) -> tuple[str, Optional[str], WorkflowStages]:
        """运行完整工作流并返回结果、事件ID和各阶段输出."""
        stages = WorkflowStages()
        state: AgentState = {
            "messages": [{"role": "user", "content": user_input}],
            "context": {},
            "task": None,
            "decision": None,
            "result": None,
            "event_id": None,
            "driving_context": driving_context,
            "stages": stages.__dict__,
        }

        for node_fn in self._nodes:
            updates = await node_fn(state)
            state.update(updates)

        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id, stages
