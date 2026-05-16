"""消融实验运行器——分发变体调用、收集结果。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from app.agents.probabilistic import (
    get_probabilistic_enabled,
    set_probabilistic_enabled,
)
from app.agents.prompts import SINGLE_LLM_SYSTEM_PROMPT
from app.agents.rules import (
    get_ablation_disable_rules,
    postprocess_decision,
    set_ablation_disable_rules,
)
from app.agents.types import WorkflowError
from app.agents.workflow import (
    AgentWorkflow,
    get_ablation_disable_feedback,
    set_ablation_disable_feedback,
)
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.models.chat import ChatError, get_chat_model

from ._io import VARIANT_TIMEOUT_SECONDS, append_checkpoint, load_checkpoint
from .config import STAGE_TIMEOUT
from .types import AblationError, BatchResult, Scenario, Variant, VariantResult

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
        elif variant == Variant.NO_SAFETY:
            set_ablation_disable_rules(True)
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
            memory_module=mm,
            current_user=user_id,
        )
        try:
            result, event_id, stages = await workflow.run_with_stages(
                scenario.user_query,
                driving_context=deepcopy(scenario.driving_context),
                stage_timeout=STAGE_TIMEOUT,
            )
        except WorkflowError:
            logger.exception(
                "[%s] variant=%s WorkflowError", scenario.id, variant.value
            )
            raise AblationError(
                code="STAGE_TIMEOUT",
                message=(
                    f"scenario={scenario.id} variant={variant.value} stage timed out"
                ),
            ) from None
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

        user_msg_data: dict[str, object] = {
            "query": scenario.user_query,
            "context": scenario.driving_context,
            "current_datetime": now,
        }
        # MemoryBank 只读检索——两变体各行隔离 memory space，保证代码路径一致，
        # 解混"架构 vs 有无记忆检索"变量。
        # 格式对齐 ContextAgent._format_memory_for_context：
        # "[event_type] text" 前缀 + 换行分隔。
        try:
            mm = get_memory_module()
            mem_results = await mm.search(
                scenario.user_query,
                top_k=5,
                user_id=_user_id,
            )
            if mem_results:
                texts: list[str] = []
                for r in mem_results:
                    content = getattr(r, "content", None) or {}
                    event_type = getattr(r, "event_type", "")
                    text = content.get("text", "") if isinstance(content, dict) else ""
                    if text:
                        prefix = f"[{event_type}] " if event_type else ""
                        texts.append(f"{prefix}{text}")
                if texts:
                    user_msg_data["memory_context"] = "\n".join(texts)
        except Exception:
            logger.debug("Memory search non-fatal for %s", scenario.id)

        user_msg = json.dumps(user_msg_data, ensure_ascii=False)
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

        def _safe_dict(val: object) -> dict[str, Any]:
            """运行时类型守卫——LLM 输出可能为列表等非 dict 类型。"""
            if isinstance(val, dict):
                return cast("dict[str, Any]", val)
            return {}

        decision = _safe_dict(output.get("decision", {}))
        modifications: list[str] = []
        driving_ctx = scenario.driving_context
        if isinstance(driving_ctx, dict) and decision:
            decision, modifications = postprocess_decision(
                decision, deepcopy(driving_ctx)
            )

        return VariantResult(
            scenario_id=scenario.id,
            variant=Variant.SINGLE_LLM,
            decision=decision,
            result_text="",
            event_id=None,
            stages={
                "context": _safe_dict(output.get("context", {})),
                "task": _safe_dict(output.get("task", {})),
                "decision": decision,
                "execution": {},
            },
            latency_ms=latency_ms,
            modifications=modifications,
        )

    async def run_batch(
        self,
        scenarios: list[Scenario],
        variants: list[Variant],
        *,
        concurrency: int = 4,
        checkpoint_path: Path | None = None,
    ) -> BatchResult:
        """批量运行场景×变体笛卡尔积（并发）。

        concurrency 控制 LLM 并发度（默认 4，匹配 provider concurrency）。
        每变体独立 user_id（{base_user_id}-{scenario.id}-{variant.value}），MemoryBank 无竞态。
        续跑先加载 checkpoint 中已有结果，再并发跑未完成的变体。
        """
        expected = len(scenarios) * len(variants)
        results: list[VariantResult] = []
        existing_ids: set[tuple[str, str]] = set()
        if checkpoint_path:
            raw_ids, raw_results, _ = await load_checkpoint(checkpoint_path)
            # 过滤 checkpoint 中不属于当前 scenarios/variants 的旧记录——
            # 若在上次 run 后修改了实验范围，旧数据不应污染本次结果。
            current_sids = {s.id for s in scenarios}
            current_vvals = {v.value for v in variants}
            existing_ids = {
                (sid, vval)
                for sid, vval in raw_ids
                if sid in current_sids and vval in current_vvals
            }
            # 按 (scenario_id, variant.value) 去重——checkpoint 中同对可能出现多行
            # （如并发追加或部分恢复），取首次出现的记录。
            seen_pairs: set[tuple[str, str]] = set()
            for r in raw_results:
                if r.scenario_id not in current_sids:
                    continue
                if r.variant.value not in current_vvals:
                    continue
                pair = (r.scenario_id, r.variant.value)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                results.append(r)

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
                    async with asyncio.timeout(VARIANT_TIMEOUT_SECONDS):
                        vr = await self.run_variant(scenario, variant, user_id=uid)
                except TimeoutError:
                    logger.warning(
                        "Variant timeout after %ds: %s %s",
                        VARIANT_TIMEOUT_SECONDS,
                        scenario.id,
                        variant.value,
                    )
                    raise
                if checkpoint_path:
                    async with ckpt_lock:
                        await append_checkpoint(
                            checkpoint_path,
                            vr,
                            include_modifications=True,
                        )
                return vr

        if not pending:
            return BatchResult(results=results, expected=expected)
        tasks = [asyncio.create_task(run_one(s, v)) for s, v in pending]
        new_results = await asyncio.gather(*tasks, return_exceptions=True)
        succeeded = [r for r in new_results if isinstance(r, VariantResult)]
        failures = [r for r in new_results if isinstance(r, Exception)]
        for r in new_results:
            if isinstance(r, BaseException) and not isinstance(r, Exception):
                if isinstance(r, asyncio.CancelledError):
                    raise r  # 传播取消语义，与 protocol.py 保持一致
                logger.error("Unexpected base exception in variant run: %s", r)
        if failures:
            failure_msgs = "; ".join(
                f"{type(f).__name__}: {f}" if str(f) else type(f).__name__
                for f in failures[:5]
            )
            logger.error(
                "%d/%d variant runs failed: %s",
                len(failures),
                len(new_results),
                failure_msgs,
            )
        return BatchResult(results=results + succeeded, expected=expected)
