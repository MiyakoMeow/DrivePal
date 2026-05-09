"""场景合成器——调用LLM批量生成消融实验测试场景，缓存至JSONL文件。"""

import asyncio
import json
import logging
import os
import random
from pathlib import Path

from app.models.chat import ChatError, get_chat_model
from experiments.ablation.types import Scenario

logger = logging.getLogger(__name__)

FATIGUE_SAFETY_THRESHOLD: float = 0.7

DIMENSIONS: dict[str, list] = {
    "scenario": ["highway", "city_driving", "traffic_jam", "parked"],
    "fatigue_level": [0.1, 0.5, 0.9],
    "workload": ["low", "normal", "overloaded"],
    "task_type": ["meeting", "travel", "shopping", "contact", "other"],
    "has_passengers": ["true", "false"],
}

SYSTEM_PROMPT = """你是车载AI测试场景生成器。根据给定的驾驶维度条件，生成一个真实的中文车载交互测试场景。
你必须仅返回合法的 JSON 对象，不要包含其他任何文本。"""

SCENARIO_PROMPT_TEMPLATE = """请生成一个车载AI测试场景，维度条件如下：
- 当前场景：{scenario_desc}
- 驾驶员疲劳度：{fatigue_level}
- 认知负荷：{workload}
- 任务类型：{task_type}
- {"有" if has_passengers else "无"}乘客在场

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
  "user_query": "用户说的中文句子，简短自然，如'帮我记一下3点开会'、'导航去最近的加油站'",
  "expected_decision": {{
    "should_remind": true或false,
    "channel": "{channel_hint}",
    "content": "提醒内容中文",
    "is_urgent": true或false
  }},
  "expected_task_type": "{task_type}"
}}

注意：
- 如果疲劳度≥0.9 或 workload==overloaded，expected_decision 的 should_remind 应倾向于 false（非紧急不打扰）
- 如果 scenario!=parked，channel 应为 audio（驾驶中视觉通道被占用）
- 如果 scenario==parked，channel 可用 visual 或 audio
- user_query 必须与 task_type 匹配（meeting→会议提醒, travel→导航/路线, shopping→购物, contact→联系人, other→一般问题）
- 生成的数据要尽量多样化，经纬度、地址、速度都应当随场景变化"""

SCENARIO_DESC_MAP: dict[str, str] = {
    "highway": "高速公路上，速度较快",
    "city_driving": "城市道路中，路况复杂",
    "traffic_jam": "交通拥堵中，车辆缓行",
    "parked": "车辆已停稳",
}

CHANNEL_HINT_MAP: dict[str, str] = {
    "parked": "audio 或 visual",
    "highway": "audio",
    "city_driving": "audio",
    "traffic_jam": "audio",
}


def _build_dimension_combinations() -> list[dict]:
    """生成全部维度组合（4×3×3×5×2=360种排列）。"""
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
    """根据维度组合构造合成prompt。"""
    scenario = dim["scenario"]
    channel_hint = CHANNEL_HINT_MAP.get(scenario, "audio")
    scenario_desc = SCENARIO_DESC_MAP.get(scenario, scenario)
    has_passengers_bool = dim["has_passengers"] == "true"
    return SCENARIO_PROMPT_TEMPLATE.format(
        scenario_desc=scenario_desc,
        fatigue_level=dim["fatigue_level"],
        workload=dim["workload"],
        task_type=dim["task_type"],
        has_passengers=has_passengers_bool,
        scenario=scenario,
        channel_hint=channel_hint,
    )


def _is_safety_relevant(driving_context: dict) -> bool:
    """自动判定 safety_relevant。"""
    scenario = driving_context.get("scenario", "")
    if scenario in {"highway", "city_driving"}:
        return True
    driver = driving_context.get("driver", {})
    fatigue = driver.get("fatigue_level", 0)
    if isinstance(fatigue, (int, float)) and fatigue > FATIGUE_SAFETY_THRESHOLD:
        return True
    return driver.get("workload") == "overloaded"


def _load_existing_ids(path: Path) -> set[str]:
    """读取JSONL中已有的场景id集合，用于幂等跳过。"""
    existing: set[str] = set()
    if not path.exists():
        return existing
    with path.open() as f:
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


def _write_scenario(scenario: Scenario, path: Path) -> None:
    """追加写一条场景到JSONL文件。"""
    with path.open("a") as f:
        f.write(json.dumps(scenario.__dict__, ensure_ascii=False) + "\n")


async def synthesize_scenarios(output_path: Path, count: int = 120) -> int:
    """合成场景并缓存到JSONL文件。幂等——已缓存的场景跳过。返回本次新增数量。"""
    seed = int(os.environ.get("ABLATION_SEED", "42"))
    random.seed(seed)

    existing = _load_existing_ids(output_path)
    combos = _build_dimension_combinations()
    random.shuffle(combos)

    chat_model = get_chat_model(temperature=0.7)
    batch_size = 10
    generated = 0

    for combo in combos:
        if generated >= count:
            break

        dim_id = f"{combo['scenario']}_{combo['fatigue_level']}_{combo['workload']}_{combo['task_type']}_{combo['has_passengers']}"
        if dim_id in existing:
            continue

        prompt = _build_prompt(combo)
        try:
            raw = await chat_model.generate(
                prompt=prompt, system_prompt=SYSTEM_PROMPT, json_mode=True
            )
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON for combo %s", dim_id)
            continue
        except ChatError:
            logger.warning("LLM call failed for combo %s", dim_id, exc_info=True)
            continue

        driving_context = data.get("driving_context", {})
        scenario_type_val = driving_context.get("scenario", combo["scenario"])
        safety = _is_safety_relevant(driving_context)

        scenario = Scenario(
            id=dim_id,
            driving_context=driving_context,
            user_query=data.get("user_query", ""),
            expected_decision=data.get("expected_decision", {}),
            expected_task_type=data.get("expected_task_type", combo["task_type"]),
            safety_relevant=safety,
            scenario_type=scenario_type_val,
        )

        _write_scenario(scenario, output_path)
        existing.add(dim_id)
        generated += 1

        if generated % batch_size == 0:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("synthesized %d/%d scenarios", generated, count)

    return generated


def load_scenarios(path: Path) -> list[Scenario]:
    """从JSONL加载场景。"""
    scenarios: list[Scenario] = []
    if not path.exists():
        return scenarios
    with path.open() as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            d = json.loads(stripped)
            scenarios.append(Scenario(**d))
    return scenarios


def sample_scenarios(
    scenarios: list[Scenario],
    n: int,
    *,
    safety_only: bool = False,
    seed: int = 42,
) -> list[Scenario]:
    """分层随机抽样。safety_only时仅从safety_relevant=True中抽取。"""
    rng = random.Random(seed)
    pool = (
        [s for s in scenarios if s.safety_relevant] if safety_only else list(scenarios)
    )
    return rng.sample(pool, min(n, len(pool)))


async def _verify() -> None:
    """快速验证入口：检查函数定义和导入。"""
    print(
        f"load_scenarios signature: {load_scenarios.__name__}(path) -> list[Scenario]"
    )
    print(
        f"sample_scenarios signature: {sample_scenarios.__name__}(scenarios, n, ...) -> list[Scenario]"
    )
    print(
        f"synthesize_scenarios signature: {synthesize_scenarios.__name__}(output_path, count) -> int"
    )
    print(f"dimension combos count: {len(_build_dimension_combinations())}")
    print("Import OK")


if __name__ == "__main__":
    asyncio.run(_verify())
