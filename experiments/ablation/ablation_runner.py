"""消融实验运行器——分发变体调用、收集结果。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

from app.agents.probabilistic import (
    get_probabilistic_enabled,
    set_probabilistic_enabled,
)
from app.agents.prompts import SINGLE_LLM_SYSTEM_PROMPT
from app.agents.rules import get_ablation_disable_rules, set_ablation_disable_rules
from app.agents.workflow import (
    AgentWorkflow,
    get_ablation_disable_feedback,
    set_ablation_disable_feedback,
)
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.models.chat import ChatError, get_chat_model

from .types import Scenario, Variant, VariantResult

logger = logging.getLogger(__name__)


class AblationRunner:
    """消融实验运行器。分发变体调用、收集结果。"""

    def __init__(self, base_user_id: str = "ablation") -> None:
        """初始化运行器。

        Args:
            base_user_id: 变体 uid 前缀。三组分别用 experiment-safety / experiment-arch / experiment-personalization。

        """
        self.base_user_id = base_user_id

    async def run_variant(
        self,
        scenario: Scenario,
        variant: Variant,
        user_id: str | None = None,
    ) -> VariantResult:
        """运行单个变体实验。user_id 传 None 则回退 base_user_id。"""
        uid = user_id or self.base_user_id
        t0 = time.perf_counter()

        # 保存原始 ContextVar 值——finally 需恢复原始值而非硬编码默认
        orig_rules = get_ablation_disable_rules()
        orig_feedback = get_ablation_disable_feedback()
        orig_prob = get_probabilistic_enabled()

        if variant == Variant.NO_RULES:
            set_ablation_disable_rules(True)
        elif variant == Variant.NO_PROB:
            set_probabilistic_enabled(False)
        elif variant == Variant.NO_FEEDBACK:
            set_ablation_disable_feedback(True)

        try:
            if variant == Variant.SINGLE_LLM:
                return await self._run_single_llm(scenario, uid, t0)
            return await self._run_agent_workflow(scenario, variant, uid, t0)
        finally:
            # 恢复原始值而非硬编码默认——尊重用户环境变量设置（如 PROBABILISTIC_INFERENCE_ENABLED=0）
            set_ablation_disable_rules(orig_rules)
            set_probabilistic_enabled(orig_prob)
            set_ablation_disable_feedback(orig_feedback)

    async def _run_agent_workflow(
        self, scenario: Scenario, variant: Variant, user_id: str, t0: float
    ) -> VariantResult:
        mm = get_memory_module()
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=MemoryMode.MEMORY_BANK,
            memory_module=mm,
            current_user=user_id,
        )
        result, event_id, stages = await workflow.run_with_stages(
            scenario.user_query,
            driving_context=deepcopy(scenario.driving_context),
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

    async def _run_single_llm(
        self, scenario: Scenario, _user_id: str, t0: float
    ) -> VariantResult:
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
        concurrency: int = 4,
        checkpoint_path: Path | None = None,
    ) -> list[VariantResult]:
        """批量运行场景×变体笛卡尔积（并发）。

        concurrency 控制 LLM 并发度（默认 4，匹配 provider concurrency）。
        每变体独立 user_id（{base_user_id}-{scenario.id}-{variant.value}），MemoryBank 无竞态。
        续跑先加载 checkpoint 中已有结果，再并发跑未完成的变体。
        """
        results: list[VariantResult] = []
        existing_ids: set[tuple[str, str]] = set()
        if checkpoint_path:
            existing_ids, existing_results = await _load_checkpoint(checkpoint_path)
            results.extend(existing_results)

        pending = [
            (s, v)
            for s in scenarios
            for v in variants
            if (s.id, v.value) not in existing_ids
        ]

        sem = asyncio.Semaphore(concurrency)
        ckpt_lock = asyncio.Lock()

        async def run_one(scenario: Scenario, variant: Variant) -> VariantResult:
            async with sem:
                uid = f"{self.base_user_id}-{scenario.id}-{variant.value}"
                try:
                    vr = await asyncio.wait_for(
                        self.run_variant(scenario, variant, user_id=uid),
                        timeout=300,
                    )
                except TimeoutError:
                    logger.exception(
                        "Variant timeout after 5min: %s %s", scenario.id, variant.value
                    )
                    raise
                if checkpoint_path:
                    async with ckpt_lock:
                        await _append_checkpoint(
                            checkpoint_path,
                            vr,
                            include_modifications=True,
                        )
                return vr

        if not pending:
            return results
        tasks = [asyncio.create_task(run_one(s, v)) for s, v in pending]
        new_results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [r for r in new_results if isinstance(r, Exception)]
        if failures:
            msg = f"{len(failures)} variant runs failed. First: {failures[0]}"
            raise RuntimeError(msg)
        return results + [r for r in new_results if isinstance(r, VariantResult)]


async def _load_checkpoint(
    path: Path,
) -> tuple[set[tuple[str, str]], list[VariantResult]]:
    """读取 JSONL checkpoint，返回 (已完成的(scenario_id,variant)集合, VariantResult 列表)。

    用于续跑：将已有结果加载回内存，避免 `dump_variant_results_jsonl` 覆盖丢失。
    """
    ids: set[tuple[str, str]] = set()
    results: list[VariantResult] = []
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            async for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                    ids.add((d["scenario_id"], d["variant"]))
                    results.append(
                        VariantResult(
                            scenario_id=d["scenario_id"],
                            variant=Variant(d["variant"]),
                            decision=d.get("decision", {}),
                            result_text=d.get("result_text", ""),
                            event_id=d.get("event_id"),
                            stages=d.get("stages", {}),
                            latency_ms=d.get("latency_ms", 0),
                            modifications=d.get("modifications", []),
                            round_index=d.get("round_index", 0),
                        )
                    )
                except json.JSONDecodeError, KeyError, ValueError:
                    logger.warning("跳过无效 checkpoint 行: %s", stripped[:80])
                    continue
    except FileNotFoundError:
        return ids, results
    return ids, results


async def _append_checkpoint(
    path: Path, vr: VariantResult, *, include_modifications: bool = False
) -> None:
    """追加写单条 VariantResult 到 checkpoint JSONL。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "scenario_id": vr.scenario_id,
        "variant": vr.variant.value,
        "decision": vr.decision,
        "stages": vr.stages,
        "latency_ms": vr.latency_ms,
        "round_index": vr.round_index,
        "result_text": vr.result_text,
        "event_id": vr.event_id,
    }
    if include_modifications:
        record["modifications"] = vr.modifications
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
