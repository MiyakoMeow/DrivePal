import json
import logging
from typing import Any, Optional, cast
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.prompts import SYSTEM_PROMPTS
from app.memory.memory import MemoryModule
from app.memory.memory_bank import MemoryBankBackend
from app.storage.json_store import JSONStore
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class AgentWorkflow:
    def __init__(
        self,
        data_dir: str = "data",
        memory_mode: str = "keyword",
        memory_module: Optional[MemoryModule] = None,
    ):
        self.data_dir = data_dir
        self.memory_mode = memory_mode

        if memory_module is not None:
            self.memory_module = memory_module
        else:
            from app.models.chat import ChatModel

            chat_model = ChatModel()
            if memory_mode == "embeddings" or memory_mode == "memorybank":
                from app.models.embedding import EmbeddingModel

                embedding_model = EmbeddingModel()
                self._embedding_model = embedding_model
                self.memory_module = MemoryModule(
                    data_dir, embedding_model=embedding_model, chat_model=chat_model
                )
            elif memory_mode == "llm_only":
                self.memory_module = MemoryModule(data_dir, chat_model=chat_model)
            else:
                self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self.memory = self.memory_module

        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """构建LangGraph工作流"""
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

    def _context_node(self, state: AgentState) -> dict:
        """Context Agent节点"""
        messages = state.get("messages", [])
        if not messages:
            user_input = ""
        else:
            user_input = str(messages[-1].content)

        try:
            related_events = (
                self.memory.search(user_input, mode=self.memory_mode)
                if user_input
                else []
            )
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            related_events = []

        try:
            relevant_memories = (
                related_events if related_events else self.memory.get_history()
            )
        except ValueError as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = related_events if related_events else []
        except Exception as e:
            logger.warning(f"Memory get_history failed: {e}")
            relevant_memories = related_events if related_events else []

        prompt = f"""{SYSTEM_PROMPTS["context"]}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象。"""

        if not self.memory.chat_model:
            raise RuntimeError("ChatModel not available for context generation")
        result = self.memory.chat_model.generate(prompt)
        try:
            context = json.loads(result)
            if not isinstance(context, dict):
                context = {"raw": result}
        except json.JSONDecodeError:
            context = {"raw": result}

        context["related_events"] = related_events
        context["relevant_memories"] = relevant_memories

        return {
            "context": context,
            "messages": state["messages"]
            + [HumanMessage(content=f"Context: {json.dumps(context)}")],
        }

    def _task_node(self, state: AgentState) -> dict:
        """Task Agent节点"""
        messages = state.get("messages", [])
        user_input = messages[-1].content if messages else ""
        context = state.get("context", {})

        prompt = f"""{SYSTEM_PROMPTS["task"]}

用户输入: {user_input}
上下文: {json.dumps(context, ensure_ascii=False)}

请输出JSON格式的任务对象。"""

        if not self.memory.chat_model:
            raise RuntimeError("ChatModel not available for task generation")
        result = self.memory.chat_model.generate(prompt)
        try:
            task = json.loads(result)
            if not isinstance(task, dict):
                task = {"raw": result}
        except json.JSONDecodeError:
            task = {"raw": result}

        return {
            "task": task,
            "messages": state["messages"]
            + [HumanMessage(content=f"Task: {json.dumps(task)}")],
        }

    def _strategy_node(self, state: AgentState) -> dict:
        """Strategy Agent节点"""
        context = state.get("context", {})
        task = state.get("task", {})

        strategies = JSONStore(self.data_dir, "strategies.json", dict).read()

        prompt = f"""{SYSTEM_PROMPTS["strategy"]}

上下文: {json.dumps(context, ensure_ascii=False)}
任务: {json.dumps(task, ensure_ascii=False)}
个性化策略: {json.dumps(strategies, ensure_ascii=False)}

请输出JSON格式的决策结果。"""

        if not self.memory.chat_model:
            raise RuntimeError("ChatModel not available for strategy generation")
        result = self.memory.chat_model.generate(prompt)
        try:
            decision = json.loads(result)
            if not isinstance(decision, dict):
                decision = {"raw": result}
        except json.JSONDecodeError:
            decision = {"raw": result}

        return {
            "decision": decision,
            "messages": state["messages"]
            + [HumanMessage(content=f"Decision: {json.dumps(decision)}")],
        }

    def _execution_node(self, state: AgentState) -> dict:
        """Execution Agent节点"""
        decision = state.get("decision", {})

        content = decision.get("content", "无提醒内容")
        event_data = {"content": content, "type": "reminder", "decision": decision}
        if self.memory_mode == "memorybank":
            event_id = self._get_memorybank_backend().write_with_memory(event_data)
        else:
            event_id = self.memory.write(event_data)
        if not event_id:
            logger.warning("Memory write returned empty event_id, using fallback")
            event_id = f"unknown_{hash(str(decision))}"

        result = f"提醒已发送: {content}"
        return {
            "result": result,
            "event_id": event_id,
            "messages": state["messages"] + [HumanMessage(content=result)],
        }

    def _get_memorybank_backend(self) -> MemoryBankBackend:
        if not hasattr(self, "_memorybank_backend") or self._memorybank_backend is None:
            self._memorybank_backend = MemoryBankBackend(
                self.data_dir,
                embedding_model=getattr(self, "_embedding_model", None),
                chat_model=self.memory.chat_model,
            )
        return self._memorybank_backend

    def run(self, user_input: str) -> tuple[str, Optional[str]]:
        """运行完整工作流，返回(result, event_id)"""
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
    data_dir: str = "data", memory_mode: str = "keyword"
) -> AgentWorkflow:
    """创建工作流实例"""
    return AgentWorkflow(data_dir, memory_mode)
