"""消融实验运行器——设置环境变量、分发变体调用、收集结果."""

import json
import logging
import os
import time
from datetime import UTC, datetime

from app.agents.prompts import SINGLE_LLM_SYSTEM_PROMPT
from app.agents.workflow import AgentWorkflow
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model

from .types import Scenario, Variant, VariantResult

logger = logging.getLogger(__name__)

ABLATION_DISABLE_RULES = "ABLATION_DISABLE_RULES"
ABLATION_DISABLE_FEEDBACK = "ABLATION_DISABLE_FEEDBACK"
PROBABILISTIC_INFERENCE_ENABLED = "PROBABILISTIC_INFERENCE_ENABLED"


class AblationRunner:
    """消融实验运行器。管理环境变量、分发变体调用、收集结果。"""

    def __init__(self, user_id: str = "ablation") -> None:
        self.user_id = user_id
        self._original_env: dict[str, str] = {}

    def _set_env(self, **kwargs: str) -> None:
        for k, v in kwargs.items():
            self._original_env.setdefault(k, os.environ.get(k, ""))
            os.environ[k] = v

    def _restore_env(self) -> None:
        for k, v in self._original_env.items():
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        self._original_env.clear()

    async def run_variant(self, scenario: Scenario, variant: Variant) -> VariantResult:
        t0 = time.perf_counter()

        if variant == Variant.NO_RULES:
            self._set_env(ABLATION_DISABLE_RULES="1")
        elif variant == Variant.NO_PROB:
            self._set_env(PROBABILISTIC_INFERENCE_ENABLED="0")
        elif variant == Variant.NO_FEEDBACK:
            self._set_env(ABLATION_DISABLE_FEEDBACK="1")

        try:
            if variant == Variant.SINGLE_LLM:
                return await self._run_single_llm(scenario, t0)
            return await self._run_agent_workflow(scenario, variant, t0)
        finally:
            self._restore_env()

    async def _run_agent_workflow(
        self, scenario: Scenario, variant: Variant, t0: float
    ) -> VariantResult:
        mm = get_memory_module()
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=MemoryMode.MEMORY_BANK,
            memory_module=mm,
            current_user=self.user_id,
        )
        result, event_id, stages = await workflow.run_with_stages(
            scenario.user_query,
            driving_context=scenario.driving_context,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return VariantResult(
            scenario_id=scenario.id,
            variant=variant,
            decision=stages.decision or {},
            result_text=result,
            event_id=event_id,
            stages={
                "context": stages.context or {},
                "task": stages.task or {},
                "decision": stages.decision or {},
                "execution": stages.execution or {},
            },
            latency_ms=latency_ms,
            modifications=stages.execution.get("modifications", [])
            if stages.execution
            else [],
        )

    async def _run_single_llm(self, scenario: Scenario, t0: float) -> VariantResult:
        chat = get_chat_model()
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        prompt = SINGLE_LLM_SYSTEM_PROMPT.format(current_datetime=now)
        user_msg = json.dumps(
            {"query": scenario.user_query, "context": scenario.driving_context},
            ensure_ascii=False,
        )
        response = await chat.generate(
            system_prompt=prompt, prompt=user_msg, json_mode=True
        )
        try:
            output = json.loads(response)
        except json.JSONDecodeError:
            logger.warning("Single-LLM returned invalid JSON for %s", scenario.id)
            output = {}
        latency_ms = (time.perf_counter() - t0) * 1000
        return VariantResult(
            scenario_id=scenario.id,
            variant=Variant.SINGLE_LLM,
            decision=output.get("decision", {}),
            result_text="",
            event_id=None,
            stages={
                "context": output.get("context", {}),
                "task": output.get("task", {}),
                "decision": output.get("decision", {}),
                "execution": {},
            },
            latency_ms=latency_ms,
        )

    async def run_batch(
        self, scenarios: list[Scenario], variants: list[Variant]
    ) -> list[VariantResult]:
        results: list[VariantResult] = []
        for scenario in scenarios:
            for variant in variants:
                results.append(await self.run_variant(scenario, variant))
        return results
