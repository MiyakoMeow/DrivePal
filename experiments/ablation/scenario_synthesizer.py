"""场景合成器——调用LLM批量生成消融实验测试场景，缓存至JSONL文件."""

import asyncio
import dataclasses
import json
import logging
import os
import random
from collections.abc import Callable
from pathlib import Path

import aiofiles

from app.models.chat import ChatError, get_chat_model

from ._io import get_fatigue_threshold
from .types import Scenario

logger = logging.getLogger(__name__)

DIMENSIONS: dict[str, list] = {
    "scenario": ["highway", "city_driving", "traffic_jam", "parked"],
    "fatigue_level": [0.1, 0.5, 0.9],
    "workload": ["low", "normal", "overloaded"],
    "task_type": ["meeting", "travel", "shopping", "contact", "other"],
    "has_passengers": ["true", "false"],
}

_NUM_DIM_FIELDS = 4

_KNOWN_SCENARIOS: frozenset[str] = frozenset(DIMENSIONS["scenario"])


def _parse_dims_from_id(dim_id: str) -> dict:
    """从场景 id 解析合成维度（旧数据兼容）.

    id 格式: {scenario}_{fatigue}_{workload}_{task_type}_{has_passengers}
    scenario 含下划线（city_driving），需用已知值前缀匹配。
    """
    for s in _KNOWN_SCENARIOS:
        prefix = s + "_"
        if dim_id.startswith(prefix):
            rest = dim_id[len(prefix) :].split("_")
            if len(rest) >= _NUM_DIM_FIELDS:
                try:
                    return {
                        "scenario": s,
                        "fatigue_level": float(rest[0]),
                        "workload": rest[1],
                        "task_type": rest[2],
                        "has_passengers": rest[3],
                    }
                except ValueError, IndexError:
                    pass
    return {}


SYSTEM_PROMPT = """你是车载AI测试场景生成器。根据给定的驾驶维度条件，生成一个真实的中文车载交互测试场景.
你必须仅返回合法的 JSON 对象，不要包含其他任何文本."""

SCENARIO_PROMPT_TEMPLATE = """请生成一个车载AI测试场景，维度条件如下：
- 当前场景：{scenario_desc}
- 驾驶员疲劳度：{fatigue_level}
- 认知负荷：{workload}
- 任务类型：{task_type}
- {passenger_text}乘客在场

返回一个 JSON 对象，格式如下：
{{
  "driving_context": {{
    "driver": {{
      "emotion": "从 neutral/anxious/fatigued/calm/angry 中选择一个匹配的",
      "workload": "{workload}",
      "fatigue_level": {fatigue_level}
    }},
    "spatial": {{
      "current_location": {{"latitude": 数字, "longitude": 数字, "address": "中文地址", "speed_kmh": 数字}},
      "destination": {{"latitude": 数字, "longitude": 数字, "address": "中文地址"}},
      "eta_minutes": 数字,
      "heading": "方向如 north/south/east/west"
    }},
    "traffic": {{
      "congestion_level": "从 smooth/slow/congested/blocked 中选择一个匹配{scenario_desc}的",
      "incidents": ["可选的事故描述"],
      "delay_minutes": 数字
    }},
    "scenario": "{scenario}"
  }},
  "user_query": "用户说的中文句子，简短自然，如'帮我记一下3点开会'、'导航去最近的加油站'"
}}

注意：
- user_query 倾向于匹配 task_type（meeting→会议提醒, travel→导航/路线, shopping→购物, contact→联系人, other→一般问题）
- 生成的数据要尽量多样化，经纬度、地址、速度都应当随场景变化"""

SCENARIO_DESC_MAP: dict[str, str] = {
    "highway": "高速公路上，速度较快",
    "city_driving": "城市道路中，路况复杂",
    "traffic_jam": "交通拥堵中，车辆缓行",
    "parked": "车辆已停稳",
}


def _build_dimension_combinations() -> list[dict]:
    """生成全部维度组合（4×3×3×5×2=360种排列）."""
    return [
        {
            "scenario": scenario,
            "fatigue_level": fatigue,
            "workload": workload,
            "task_type": task_type,
            "has_passengers": has_p,
        }
        for scenario in DIMENSIONS["scenario"]
        for fatigue in DIMENSIONS["fatigue_level"]
        for workload in DIMENSIONS["workload"]
        for task_type in DIMENSIONS["task_type"]
        for has_p in DIMENSIONS["has_passengers"]
    ]


def _build_prompt(dim: dict) -> str:
    """根据维度组合构造合成prompt."""
    scenario = dim["scenario"]
    scenario_desc = SCENARIO_DESC_MAP.get(scenario, scenario)
    has_passengers_bool = dim["has_passengers"] == "true"
    passenger_text = "有" if has_passengers_bool else "无"
    return SCENARIO_PROMPT_TEMPLATE.format(
        scenario_desc=scenario_desc,
        fatigue_level=dim["fatigue_level"],
        workload=dim["workload"],
        task_type=dim["task_type"],
        passenger_text=passenger_text,
        scenario=scenario,
    )


def _compute_safety_relevant(dim: dict) -> bool:
    """从合成维度判定安全相关性——highway / 高疲劳 / 过载."""
    scenario = dim["scenario"]
    if scenario == "highway":
        return True
    fatigue = dim["fatigue_level"]
    if isinstance(fatigue, (int, float)) and fatigue > get_fatigue_threshold():
        return True
    return dim["workload"] == "overloaded"


def _load_existing_ids(path: Path) -> set[str]:
    """读取JSONL中已有的场景id集合，用于幂等跳过.

    场景文件通常很小（≤360 行），同步读取无性能影响。
    """
    existing: set[str] = set()
    if not path.exists():
        return existing
    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if "id" in obj:
                    existing.add(obj["id"])
            except json.JSONDecodeError:
                continue
    return existing


async def _write_scenario(scenario: Scenario, path: Path) -> None:
    """追加写一条场景到JSONL文件."""
    async with aiofiles.open(path, "a") as f:
        await f.write(
            json.dumps(dataclasses.asdict(scenario), ensure_ascii=False) + "\n"
        )


async def synthesize_scenarios(output_path: Path, count: int = 260) -> int:
    """合成场景并缓存到JSONL文件。幂等——已缓存的场景跳过。返回本次新增数量."""
    seed = int(os.environ.get("ABLATION_SEED", "42"))
    rng = random.Random(seed)

    existing = _load_existing_ids(output_path)
    combos = _build_dimension_combinations()
    rng.shuffle(combos)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    chat_model = get_chat_model(temperature=0.7)
    sem = asyncio.Semaphore(8)
    write_lock = asyncio.Lock()
    generated_count = 0
    log_interval = 10

    async def _synthesize_one(combo: dict) -> int:
        nonlocal generated_count
        dim_id = f"{combo['scenario']}_{combo['fatigue_level']}_{combo['workload']}_{combo['task_type']}_{combo['has_passengers']}"
        if dim_id in existing:
            return 0
        # 注：dim_id 来自 _build_dimension_combinations() 的 360 种唯一排列，
        # 无两 task 共享同 dim_id，故此检查在锁外安全。

        # 早退：已达目标数量则跳过，避免浪费 LLM 调用
        # generated_count 只增不减，无锁读取可能滞后，最多多调 sem 容量次 LLM
        if generated_count >= count:
            return 0

        async with sem:
            prompt = _build_prompt(combo)
            try:
                raw = await chat_model.generate(
                    prompt=prompt, system_prompt=SYSTEM_PROMPT, json_mode=True
                )
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON for combo %s", dim_id)
                return 0
            except ChatError:
                logger.warning("LLM call failed for combo %s", dim_id, exc_info=True)
                return 0

            driving_context = data.get("driving_context", {})
            if not isinstance(driving_context, dict):
                driving_context = {}
            scenario_type_val = driving_context.get("scenario", combo["scenario"])
            safety = _compute_safety_relevant(combo)

            scenario = Scenario(
                id=dim_id,
                driving_context=driving_context,
                user_query=data.get("user_query", ""),
                expected_decision=data.get("expected_decision", {}),
                expected_task_type=data.get("expected_task_type", combo["task_type"]),
                safety_relevant=safety,
                scenario_type=scenario_type_val,
                synthesis_dims=combo,
            )

            async with write_lock:
                current_total = generated_count
                if current_total >= count:
                    return 0
                await _write_scenario(scenario, output_path)
                existing.add(dim_id)
                generated_count += 1

        if generated_count % log_interval == 0:
            logger.info("synthesized %d/%d scenarios", generated_count, count)
        return 1

    tasks = [_synthesize_one(c) for c in combos]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = sum(1 for r in results if isinstance(r, Exception))
    if failures:
        logger.warning("%d synthesis tasks failed", failures)
    return generated_count


def load_scenarios(path: Path) -> list[Scenario]:
    """从JSONL加载场景。场景文件通常很小，同步读取无性能影响."""
    scenarios: list[Scenario] = []
    if not path.exists():
        return scenarios
    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                d = json.loads(stripped)
                if "synthesis_dims" not in d or not d["synthesis_dims"]:
                    d["synthesis_dims"] = _parse_dims_from_id(d.get("id", ""))
                scenarios.append(Scenario(**d))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("跳过无效场景行: %s", e)
                continue
    return scenarios


def sample_scenarios(
    scenarios: list[Scenario],
    n: int,
    *,
    safety_only: bool = False,
    exclude_ids: set[str] | None = None,
    stratify_key: Callable[[Scenario], str] | None = None,
    min_per_stratum: int = 1,
    seed: int = 42,
) -> list[Scenario]:
    """分层随机抽样。safety_only时仅从safety_relevant=True中抽取.

    stratify_key 提供时，先保证每层至少 min_per_stratum 个样本，
    再随机补足至 n 个，避免简单随机导致某些 strata 缺失。
    exclude_ids 用于组间互斥——同一场景不进入多组实验。
    """
    rng = random.Random(seed)
    pool = (
        [s for s in scenarios if s.safety_relevant] if safety_only else list(scenarios)
    )
    if exclude_ids:
        pool = [s for s in pool if s.id not in exclude_ids]

    if not pool:
        raise ValueError("过滤/排除后无可用的场景")

    if not stratify_key or len(pool) <= n:
        return rng.sample(pool, min(n, len(pool)))

    strata: dict[str, list[Scenario]] = {}
    for s in pool:
        key = stratify_key(s)
        strata.setdefault(key, []).append(s)

    required = sum(min(min_per_stratum, len(g)) for g in strata.values())
    if required > n:
        raise ValueError(
            f"无法满足 min_per_stratum={min_per_stratum}，"
            f"实际需要 {required} 个样本（考虑各层容量），但仅请求 {n} 个"
        )

    result: list[Scenario] = []
    sampled_ids: set[str] = set()

    for group in strata.values():
        k = min(min_per_stratum, len(group))
        sampled = rng.sample(group, k)
        result.extend(sampled)
        sampled_ids.update(s.id for s in sampled)

    remaining = [s for s in pool if s.id not in sampled_ids]
    deficit = n - len(result)
    if deficit > 0 and remaining:
        extra = rng.sample(remaining, min(deficit, len(remaining)))
        result.extend(extra)

    rng.shuffle(result)
    return result[:n]
