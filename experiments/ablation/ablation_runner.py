"""消融实验运行器——设置环境变量、分发变体调用、收集结果."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

from app.agents.prompts import SINGLE_LLM_SYSTEM_PROMPT
from app.agents.rules import set_ablation_disable_rules
from app.agents.workflow import AgentWorkflow, set_ablation_disable_feedback
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.models.chat import ChatError, get_chat_model

from .types import Scenario, Variant, VariantResult

logger = logging.getLogger(__name__)

PROBABILISTIC_INFERENCE_ENABLED = "PROBABILISTIC_INFERENCE_ENABLED"


class AblationRunner:
    """消融实验运行器。管理环境变量、分发变体调用、收集结果。"""

    def __init__(self, user_id: str = "ablation") -> None:
        """初始化运行器。

        Args:
            user_id: 实验用用户标识，默认 ablation。

        """
        self.user_id = user_id
        self._original_env: dict[str, str | None] = {}

    def _set_env(self, **kwargs: str) -> None:
        for k, v in kwargs.items():
            self._original_env.setdefault(k, os.environ.get(k))
            os.environ[k] = v

    def _restore_env(self) -> None:
        for k, v in self._original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._original_env.clear()

    async def run_variant(self, scenario: Scenario, variant: Variant) -> VariantResult:
        """运行单个变体实验。设置环境变量，分发到 workflow 或单 LLM 路径。"""
        t0 = time.perf_counter()

        if variant == Variant.NO_RULES:
            set_ablation_disable_rules(True)
        elif variant == Variant.NO_PROB:
            self._set_env(PROBABILISTIC_INFERENCE_ENABLED="0")
        elif variant == Variant.NO_FEEDBACK:
            set_ablation_disable_feedback(True)

        try:
            if variant == Variant.SINGLE_LLM:
                return await self._run_single_llm(scenario, t0)
            return await self._run_agent_workflow(scenario, variant, t0)
        finally:
            if variant == Variant.NO_RULES:
                set_ablation_disable_rules(False)
            elif variant == Variant.NO_FEEDBACK:
                set_ablation_disable_feedback(False)
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
        try:
            response = await chat.generate(
                system_prompt=prompt, prompt=user_msg, json_mode=True
            )
            try:
                output = json.loads(response)
            except json.JSONDecodeError:
                logger.warning("Single-LLM returned invalid JSON for %s", scenario.id)
                output = {}
        except ChatError:
            logger.warning("Single-LLM chat failed for %s", scenario.id, exc_info=True)
            output = {"error": "LLM调用失败"}
        if not isinstance(output, dict):
            output = {}
        latency_ms = (time.perf_counter() - t0) * 1000
        return VariantResult(
            scenario_id=scenario.id,
            variant=Variant.SINGLE_LLM,
            decision=cast("dict", output.get("decision", {})),
            result_text="",
            event_id=None,
            stages={
                "context": cast("dict", output.get("context", {})),
                "task": cast("dict", output.get("task", {})),
                "decision": cast("dict", output.get("decision", {})),
                "execution": {},
            },
            latency_ms=latency_ms,
        )

    async def run_batch(
        self,
        scenarios: list[Scenario],
        variants: list[Variant],
        *,
        checkpoint_path: Path | None = None,
    ) -> list[VariantResult]:
        """批量运行场景×变体笛卡尔积。checkpoint_path 指定则增量写 JSONL。"""
        results: list[VariantResult] = []
        existing_ids: set[tuple[str, str]] = (
            await _load_checkpoint_ids(checkpoint_path) if checkpoint_path else set()
        )
        for scenario in scenarios:
            for variant in variants:
                if (scenario.id, variant.value) in existing_ids:
                    continue
                vr = await self.run_variant(scenario, variant)
                results.append(vr)
                if checkpoint_path:
                    existing_ids.add((scenario.id, variant.value))
                    await _append_checkpoint(checkpoint_path, vr)
        return results


async def _load_checkpoint_ids(path: Path) -> set[tuple[str, str]]:
    """读取 JSONL 中已完成的 (scenario_id, variant) 对。"""
    existing: set[tuple[str, str]] = set()
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            async for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                    existing.add((d["scenario_id"], d["variant"]))
                except json.JSONDecodeError, KeyError:
                    logger.warning("跳过无效 checkpoint 行: %s", stripped[:80])
                    continue
    except FileNotFoundError:
        return existing
    return existing


async def _append_checkpoint(
    path: Path, vr: VariantResult, *, include_modifications: bool = False
) -> None:
    """追加写单条 VariantResult 到 checkpoint JSONL。"""
    record: dict[str, object] = {
        "scenario_id": vr.scenario_id,
        "variant": vr.variant.value,
        "decision": vr.decision,
        "stages": vr.stages,
        "latency_ms": vr.latency_ms,
        "round_index": vr.round_index,
    }
    if include_modifications:
        record["modifications"] = vr.modifications
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(record, ensure_ascii=False) + "\n")
