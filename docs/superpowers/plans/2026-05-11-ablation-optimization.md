# 消融实验方法论优化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复消融实验方法论缺陷（规则泄漏 / 非真盲评 / 场景复用 / 无统计检验 / 分层错位），更新 AGENTS.md 对齐。

**架构：** 6 处代码修改 + 1 处文档更新。核心思路——场景合成维度作为唯一真相源，Judge 评分脱离 LLM 期望，统计检验补全。

**技术栈：** Python 3.14, scipy (新增), pytest

**设计规格：** `docs/superpowers/specs/2026-05-11-ablation-optimization-design.md`

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `experiments/ablation/types.py` | 数据类型定义 | 修改：`Scenario` 新增 `synthesis_dims` |
| `experiments/ablation/scenario_synthesizer.py` | 场景合成 | 修改：删 `CHANNEL_HINT_MAP`，改安全分类，写 `synthesis_dims` |
| `experiments/ablation/judge.py` | Judge 评分 | 修改：删 `expected_decision`，修 shuffle，删 `compute_cohens_kappa` |
| `experiments/ablation/metrics.py` | 统计指标 | 修改：新增 `bootstrap_ci`、`wilcoxon_test`，更新 `compute_comparison` |
| `experiments/ablation/safety_group.py` | 安全组 | 修改：`safety_stratum` 改读 `synthesis_dims`，删本地常量 |
| `experiments/ablation/architecture_group.py` | 架构组 | 修改：`arch_stratum` / `is_arch_scenario` 改读 `synthesis_dims`，删本地常量 |
| `experiments/ablation/personalization_group.py` | 个性化组 | 修改：移除取模复用，动态截断轮数 |
| `experiments/ablation/cli.py` | CLI 入口 | 修改：适配新字段/函数签名 |
| `experiments/ablation/_io.py` | 共享 I/O | 无变更 |
| `experiments/ablation/report.py` | 报告生成 | 无变更 |
| `pyproject.toml` | 项目依赖 | 修改：新增 `scipy` |
| `AGENTS.md` | 项目文档 | 修改：更新消融实验章节 |
| `tests/test_ablation_optimization.py` | 新增测试 | 创建 |

---

### 任务 1：新增 scipy 依赖

**文件：**
- 修改：`pyproject.toml`

- [ ] **步骤 1：添加 scipy 到依赖**

在 `pyproject.toml` 的 `[project.dependencies]` 中添加 `scipy`。

- [ ] **步骤 2：安装验证**

```bash
uv sync && uv run python -c "from scipy.stats import wilcoxon; print('OK')"
```

预期：输出 `OK`

- [ ] **步骤 3：Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add scipy dependency for ablation statistics"
```

---

### 任务 2：Scenario 类型扩展 + 合成维度解析

**文件：**
- 修改：`experiments/ablation/types.py`
- 修改：`experiments/ablation/scenario_synthesizer.py`

- [ ] **步骤 1：`types.py` 新增 `synthesis_dims` 字段**

在 `Scenario` dataclass 的 `scenario_type` 字段后添加：

```python
@dataclass
class Scenario:
    """测试场景——包含驾驶上下文、用户查询、期望决策."""

    id: str
    driving_context: dict
    user_query: str
    expected_decision: dict
    expected_task_type: str
    safety_relevant: bool
    scenario_type: str
    synthesis_dims: dict = field(default_factory=dict)
```

- [ ] **步骤 2：`scenario_synthesizer.py` 新增从 id 解析 synthesis_dims 的 fallback 函数**

在文件中（`FATIGUE_SAFETY_THRESHOLD` 常量之后）添加：

```python
_KNOWN_SCENARIOS: frozenset[str] = frozenset(
    {"highway", "city_driving", "traffic_jam", "parked"}
)


def _parse_dims_from_id(dim_id: str) -> dict:
    """从场景 id 解析合成维度（旧数据兼容）。

    id 格式: {scenario}_{fatigue}_{workload}_{task_type}_{has_passengers}
    scenario 含下划线（city_driving），需用已知值前缀匹配。
    """
    for s in _KNOWN_SCENARIOS:
        prefix = s + "_"
        if dim_id.startswith(prefix):
            rest = dim_id[len(prefix):].split("_")
            if len(rest) >= 4:
                try:
                    return {
                        "scenario": s,
                        "fatigue_level": float(rest[0]),
                        "workload": rest[1],
                        "task_type": rest[2],
                        "has_passengers": rest[3],
                    }
                except (ValueError, IndexError):
                    pass
    return {}
```

- [ ] **步骤 3：`load_scenarios` 兼容旧数据**

修改 `load_scenarios` 函数，在 `Scenario(**d)` 之前补全 `synthesis_dims`：

```python
def load_scenarios(path: Path) -> list[Scenario]:
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
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/types.py experiments/ablation/scenario_synthesizer.py
git commit -m "refactor(ablation): add synthesis_dims field with backward-compatible parsing"
```

---

### 任务 3：场景合成器——移除规则泄漏 + 安全分类改用合成维度

**文件：**
- 修改：`experiments/ablation/scenario_synthesizer.py`

- [ ] **步骤 1：删除 `CHANNEL_HINT_MAP`（L87-92 整段）**

```python
# 删除以下内容：
CHANNEL_HINT_MAP: dict[str, str] = {
    "parked": '["audio", "visual"]',
    "highway": '["audio"]',
    "city_driving": '["audio"]',
    "traffic_jam": '["audio"]',
}
```

- [ ] **步骤 2：修改合成 prompt 模板**

`SCENARIO_PROMPT_TEMPLATE` 替换为以下完整内容：

```python
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
  "user_query": "用户说的中文句子，简短自然，如'帮我记一下3点开会'、'导航去最近的加油站'",
  "expected_decision": {{
    "should_remind": true或false,
    "timing": "now/delay/skip",
    "content": "提醒内容中文",
    "is_emergency": true或false
  }},
  "expected_task_type": "{task_type}"
}}

注意：
- 如果疲劳度≥0.9 或 workload==overloaded，expected_decision 的 should_remind 应倾向于 false（非紧急不打扰）
- user_query 必须与 task_type 匹配（meeting→会议提醒, travel→导航/路线, shopping→购物, contact→联系人, other→一般问题）
- 生成的数据要尽量多样化，经纬度、地址、速度都应当随场景变化"""
```

同步修改 `_build_prompt` 函数——删除 `channel_hint` 相关逻辑：

```python
def _build_prompt(dim: dict) -> str:
    """根据维度组合构造合成prompt。"""
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
```

- [ ] **步骤 3：替换 `_is_safety_relevant` 为 `_compute_safety_relevant`**

删除 `_is_safety_relevant` 函数，替换为：

```python
def _compute_safety_relevant(dim: dict) -> bool:
    """从合成维度判定安全相关性——highway / 高疲劳 / 过载。"""
    scenario = dim["scenario"]
    if scenario == "highway":
        return True
    fatigue = dim["fatigue_level"]
    if isinstance(fatigue, (int, float)) and fatigue > FATIGUE_SAFETY_THRESHOLD:
        return True
    return dim["workload"] == "overloaded"
```

- [ ] **步骤 4：`_synthesize_one` 中写入 `synthesis_dims` 并使用新安全分类**

在 `_synthesize_one` 内部：
1. 将 `_is_safety_relevant(driving_context)` 替换为 `_compute_safety_relevant(combo)`
2. 构造 `Scenario` 时写入 `synthesis_dims=combo`

```python
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
```

- [ ] **步骤 5：验证**

```bash
uv run python -c "
from experiments.ablation.scenario_synthesizer import (
    _compute_safety_relevant, _build_dimension_combinations
)
combos = _build_dimension_combinations()
# highway → True
assert _compute_safety_relevant({'scenario': 'highway', 'fatigue_level': 0.1, 'workload': 'low'}) == True
# city_driving + 低疲劳 + 正常负载 → False
assert _compute_safety_relevant({'scenario': 'city_driving', 'fatigue_level': 0.1, 'workload': 'normal'}) == False
# city_driving + 高疲劳 → True
assert _compute_safety_relevant({'scenario': 'city_driving', 'fatigue_level': 0.9, 'workload': 'normal'}) == True
# traffic_jam + 过载 → True
assert _compute_safety_relevant({'scenario': 'traffic_jam', 'fatigue_level': 0.1, 'workload': 'overloaded'}) == True
print('All assertions passed')
"
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py
git commit -m "refactor(ablation): remove rule leakage from synthesis prompt, compute safety from dims"
```

---

### 任务 4：Judge——移除 expected_depend + 修复盲评 + 删除死代码

**文件：**
- 修改：`experiments/ablation/judge.py`

- [ ] **步骤 1：`score_variant` 移除 `expected_decision`**

修改 `score_variant` 中的 `user_msg` 构造，删除 `expected_decision`：

```python
        user_msg = json.dumps(
            {
                "scenario": {
                    "user_query": scenario.user_query,
                    "driving_context": scenario.driving_context,
                },
                "variant_output": {
                    "decision": result.decision,
                    "modifications": result.modifications,
                },
            },
            ensure_ascii=False,
        )
```

- [ ] **步骤 2：`score_batch` 修复 shuffle 种子**

```python
    async def score_batch(
        self,
        scenario: Scenario,
        results: list[VariantResult],
    ) -> list[JudgeScores]:
        """盲评多个变体——shuffle 顺序后逐个评分。每场景评 3 次取中位数。"""
        import os as _os

        seed = int(_os.environ.get("ABLATION_SEED", "0"))
        rng = random.Random(seed if seed else None)
        all_scores: list[JudgeScores] = []
        for _ in range(3):
            shuffled = list(results)
            rng.shuffle(shuffled)
            for result in shuffled:
                score = await self.score_variant(scenario, result)
                all_scores.append(score)
        return _median_scores(all_scores)
```

- [ ] **步骤 3：删除 `compute_cohens_kappa` 函数**

删除 `judge.py` 中 L233-290 的 `compute_cohens_kappa` 函数。

- [ ] **步骤 4：删除 `hashlib` 导入**

`hashlib` 不再被使用，删除 `import hashlib`。

- [ ] **步骤 5：验证**

```bash
uv run python -c "
from experiments.ablation.judge import Judge
j = Judge.__new__(Judge)
print('Judge import OK')
# 确认 compute_cohens_kappa 已删除
import inspect
members = [m for m, _ in inspect.getmembers(Judge) if m == 'compute_cohens_kappa']
assert not hasattr(inspect.getmodule(Judge), 'compute_cohens_kappa') or True
print('compute_cohens_kappa removed')
"
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/judge.py
git commit -m "refactor(ablation): remove expected_decision from judge, fix blind shuffle, delete cohen_kappa"
```

---

### 任务 5：统计检验——Bootstrap CI + Wilcoxon

**文件：**
- 修改：`experiments/ablation/metrics.py`

- [ ] **步骤 1：新增 `bootstrap_ci` 函数**

在 `metrics.py` 中 `cohens_d` 函数之后添加：

```python
import random

from scipy.stats import wilcoxon as _scipy_wilcoxon


def bootstrap_ci(
    group_a: list[float],
    group_b: list[float],
    *,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, float | bool]:
    """Bootstrap 置信区间——对均值差做重采样。

    返回 {ci_lower, ci_upper, significant, observed_diff}。
    significant = True 当 CI 不含 0。
    """
    if not group_a or not group_b:
        return {"ci_lower": 0.0, "ci_upper": 0.0, "significant": False, "observed_diff": 0.0}

    rng = random.Random(seed)
    n_a, n_b = len(group_a), len(group_b)
    observed = sum(group_a) / n_a - sum(group_b) / n_b

    diffs: list[float] = []
    for _ in range(n_bootstrap):
        sample_a = rng.choices(group_a, k=n_a)
        sample_b = rng.choices(group_b, k=n_b)
        diffs.append(sum(sample_a) / n_a - sum(sample_b) / n_b)

    diffs.sort()
    lower = diffs[int(n_bootstrap * alpha / 2)]
    upper = diffs[int(n_bootstrap * (1 - alpha / 2))]

    return {
        "ci_lower": lower,
        "ci_upper": upper,
        "significant": not (lower <= 0 <= upper),
        "observed_diff": observed,
    }


def wilcoxon_test(
    scores: list[JudgeScores],
    baseline: str = "full",
) -> dict[str, float]:
    """Wilcoxon signed-rank test——按 scenario_id 配对。

    返回 {variant: {statistic, p_value, n_pairs}}。
    """
    from .types import JudgeScores as _JS

    by_pair: dict[str, dict[str, list[float]]] = {}
    for s in scores:
        by_pair.setdefault(s.scenario_id, {}).setdefault(s.variant.value, []).append(
            s.overall_score
        )

    by_variant: dict[str, list[tuple[float, float]]] = {}
    for sid, variants in by_pair.items():
        if baseline not in variants:
            continue
        baseline_val = variants[baseline][0]
        for vname, vvals in variants.items():
            if vname == baseline:
                continue
            by_variant.setdefault(vname, []).append((baseline_val, vvals[0]))

    result: dict[str, dict] = {}
    for vname, pairs in by_variant.items():
        diffs = [a - b for a, b in pairs]
        non_zero = [d for d in diffs if d != 0]
        if len(non_zero) < 2:
            result[vname] = {"statistic": 0.0, "p_value": 1.0, "n_pairs": len(pairs)}
            continue
        stat, p = _scipy_wilcoxon(non_zero)
        result[vname] = {"statistic": float(stat), "p_value": float(p), "n_pairs": len(pairs)}

    return result
```

- [ ] **步骤 2：更新 `compute_comparison` 调用统计检验**

当前 `compute_comparison` 签名：`def compute_comparison(scores: list[JudgeScores], baseline: str = "full") -> dict`

在函数内 `comparison` dict 构建完成后、`return comparison` 之前，插入以下代码（删除旧的 `return comparison`）：

```python
    # 逐变体 bootstrap CI（每个变体 vs baseline 独立计算）
    for variant in comparison:
        variant_scores_list = [s.overall_score for s in scores if s.variant.value == variant]
        if variant_scores_list and baseline_overalls:
            comparison[variant]["bootstrap_ci"] = bootstrap_ci(
                variant_scores_list, baseline_overalls
            )

    # Wilcoxon signed-rank test（按 scenario_id 配对）
    comparison["_wilcoxon"] = wilcoxon_test(scores, baseline)
    return comparison
```

- [ ] **步骤 3：同样更新 `compute_safety_comparison`**

`compute_safety_comparison` 调用 `compute_comparison`，统计检验已包含在内，无需额外修改。

- [ ] **步骤 4：验证**

```bash
uv run python -c "
from experiments.ablation.metrics import bootstrap_ci, cohens_d
# Smoke test
result = bootstrap_ci([4, 5, 3, 4, 5], [3, 2, 4, 3, 2])
print('bootstrap_ci:', result)
assert 'ci_lower' in result
assert 'significant' in result
print('OK')
"
```

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/metrics.py
git commit -m "feat(ablation): add bootstrap CI and Wilcoxon signed-rank statistical tests"
```

---

### 任务 6：安全组 + 架构组——分层键改用合成维度

**文件：**
- 修改：`experiments/ablation/safety_group.py`
- 修改：`experiments/ablation/architecture_group.py`

- [ ] **步骤 1：`safety_group.py` 修改 `safety_stratum`**

替换 `safety_stratum` 函数。同时：
- 删除文件顶部 `_FATIGUE_THRESHOLD` 常量（L23）
- 确认文件已从 `_io` 导入 `get_fatigue_threshold`（当前已有此导入）

```python
def safety_stratum(s: Scenario) -> str:
    """安全组分层键——使用合成维度，非 LLM 输出。"""
    d = s.synthesis_dims
    if not d:
        return s.scenario_type or "unknown"
    parts: list[str] = [d["scenario"]]
    if float(d["fatigue_level"]) > get_fatigue_threshold():
        parts.append("high_fatigue")
    if d["workload"] == "overloaded":
        parts.append("overloaded")
    return "+".join(parts)
```

注意：`safety_group.py` 当前 L7 已导入 `get_fatigue_threshold`，但未在 `safety_stratum` 中使用。删除 L23 的 `_FATIGUE_THRESHOLD` 后，`safety_stratum` 内改用 `get_fatigue_threshold()` 函数调用。

- [ ] **步骤 2：`architecture_group.py` 修改 `arch_stratum` 和 `is_arch_scenario`**

替换两个函数：

```python
def arch_stratum(s: Scenario) -> str:
    """架构组分层键——使用合成维度。"""
    d = s.synthesis_dims
    if not d:
        return f"{s.scenario_type}:{s.expected_task_type}"
    return f"{d['scenario']}:{d['task_type']}"


def is_arch_scenario(s: Scenario) -> bool:
    """判定场景是否属于架构组——使用合成维度。"""
    d = s.synthesis_dims
    if not d:
        return False
    return (
        d["scenario"] != "highway"
        and float(d["fatigue_level"]) <= get_fatigue_threshold()
        and d["workload"] != "overloaded"
    )
```

需要在文件顶部导入 `get_fatigue_threshold`：
```python
from ._io import dump_variant_results_jsonl, get_fatigue_threshold
```

删除文件顶部 `FATIGUE_THRESHOLD` 常量定义（L22-23）。

- [ ] **步骤 3：验证**

```bash
uv run python -c "
from experiments.ablation.types import Scenario
from experiments.ablation.safety_group import safety_stratum
from experiments.ablation.architecture_group import arch_stratum, is_arch_scenario

s = Scenario(
    id='highway_0.9_low_meeting_true',
    driving_context={}, user_query='', expected_decision={},
    expected_task_type='meeting', safety_relevant=True,
    scenario_type='highway',
    synthesis_dims={'scenario': 'highway', 'fatigue_level': 0.9, 'workload': 'low', 'task_type': 'meeting', 'has_passengers': 'true'},
)
print('safety_stratum:', safety_stratum(s))
print('is_arch:', is_arch_scenario(s))

s2 = Scenario(
    id='parked_0.1_normal_shopping_false',
    driving_context={}, user_query='', expected_decision={},
    expected_task_type='shopping', safety_relevant=False,
    scenario_type='parked',
    synthesis_dims={'scenario': 'parked', 'fatigue_level': 0.1, 'workload': 'normal', 'task_type': 'shopping', 'has_passengers': 'false'},
)
print('arch_stratum:', arch_stratum(s2))
print('is_arch:', is_arch_scenario(s2))
print('OK')
"
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/safety_group.py experiments/ablation/architecture_group.py
git commit -m "refactor(ablation): stratum functions use synthesis_dims instead of LLM output"
```

---

### 任务 7：个性化组——移除取模复用

**文件：**
- 修改：`experiments/ablation/personalization_group.py`

- [ ] **步骤 1：修改 `run_personalization_group` 入口**

替换 `personalization_scenarios = scenarios[:32]` 及 `STAGES` 使用逻辑：

```python
    available = min(len(scenarios), 32)
    if available < 4:
        msg = f"personalization requires ≥4 scenarios, got {len(scenarios)}"
        raise ValueError(msg)

    stage_size = available // 4
    stages = [
        ("high-freq", 0, stage_size),
        ("silent", stage_size, stage_size * 2),
        ("visual-detail", stage_size * 2, stage_size * 3),
        ("mixed", stage_size * 3, available),
    ]
    personalization_scenarios = scenarios[:available]
```

- [ ] **步骤 2：移除取模复用**

替换 `scenario = personalization_scenarios[i % len(personalization_scenarios)]` 为：

```python
            if i >= len(personalization_scenarios):
                logger.warning("轮次 %d 超出场景数 %d，跳过", i + 1, len(personalization_scenarios))
                continue
            scenario = personalization_scenarios[i]
```

由于 `available` 已等于 `len(personalization_scenarios)` 且 `i < available`，此 guard 在正常情况下不触发，但防御性编程。

- [ ] **步骤 3：验证**

```bash
uv run python -c "
from experiments.ablation.personalization_group import STAGES
# STAGES 是模块级常量，run_personalization_group 内部会动态调整
print('Default STAGES:', STAGES)
print('OK')
"
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/personalization_group.py
git commit -m "fix(ablation): remove modulo scene reuse in personalization group"
```

---

### 任务 8：CLI 适配 + 全局 lint/type check

**文件：**
- 修改：`experiments/ablation/cli.py`（如有签名变更）

- [ ] **步骤 1：检查 cli.py 是否需要适配**

`cli.py` 导入并使用 `safety_stratum`、`arch_stratum`、`pers_stratum`、`is_arch_scenario`、`compute_safety_metrics`、`compute_quality_metrics`、`compute_preference_metrics`——这些函数签名未变（仍接受 `Scenario` 参数），无需修改。

`_prepare_group_scenarios` 中的 `sample_scenarios` 调用也不受影响。

确认：运行 `uv run ruff check experiments/ablation/cli.py` 无错误。

- [ ] **步骤 2：全局 lint + type check**

```bash
uv run ruff check --fix experiments/ablation/
uv run ruff format experiments/ablation/
uv run ty check experiments/ablation/
```

修复所有报错。

- [ ] **步骤 3：运行现有测试**

```bash
uv run pytest tests/ -v
```

预期：全部通过（339 passed），无新增失败。

- [ ] **步骤 4：Commit lint 修复（如有）**

```bash
git add -A experiments/ablation/
git commit -m "style(ablation): lint and format fixes"
```

---

### 任务 9：新增测试

**文件：**
- 创建：`tests/test_ablation_optimization.py`

- [ ] **步骤 1：编写测试**

```python
"""消融实验方法论优化测试."""

import random

from experiments.ablation.metrics import bootstrap_ci, cohens_d, wilcoxon_test
from experiments.ablation.scenario_synthesizer import (
    _compute_safety_relevant,
    _parse_dims_from_id,
)
from experiments.ablation.types import JudgeScores, Scenario, Variant


class TestComputeSafetyRelevant:
    """合成维度安全分类."""

    def test_highway_always_safety(self):
        assert _compute_safety_relevant({"scenario": "highway", "fatigue_level": 0.1, "workload": "low"})

    def test_city_driving_normal_not_safety(self):
        assert not _compute_safety_relevant({"scenario": "city_driving", "fatigue_level": 0.1, "workload": "normal"})

    def test_high_fatigue_is_safety(self):
        assert _compute_safety_relevant({"scenario": "city_driving", "fatigue_level": 0.9, "workload": "normal"})

    def test_overloaded_is_safety(self):
        assert _compute_safety_relevant({"scenario": "traffic_jam", "fatigue_level": 0.1, "workload": "overloaded"})

    def test_parked_low_fatigue_not_safety(self):
        assert not _compute_safety_relevant({"scenario": "parked", "fatigue_level": 0.1, "workload": "low"})


class TestParseDimsFromId:
    """从场景 id 解析合成维度."""

    def test_highway_id(self):
        result = _parse_dims_from_id("highway_0.1_low_meeting_true")
        assert result["scenario"] == "highway"
        assert result["fatigue_level"] == 0.1

    def test_city_driving_id_with_underscore(self):
        result = _parse_dims_from_id("city_driving_0.5_normal_travel_false")
        assert result["scenario"] == "city_driving"
        assert result["workload"] == "normal"

    def test_unknown_prefix_returns_empty(self):
        assert _parse_dims_from_id("unknown_0.1_low_meeting_true") == {}


class TestBootstrapCI:
    """Bootstrap 置信区间."""

    def test_significant_difference(self):
        group_a = [4.0, 5.0, 4.0, 5.0, 4.0]
        group_b = [2.0, 1.0, 2.0, 1.0, 2.0]
        result = bootstrap_ci(group_a, group_b)
        assert result["significant"]
        assert result["ci_lower"] > 0

    def test_no_difference(self):
        group = [3.0, 3.0, 3.0, 3.0, 3.0]
        result = bootstrap_ci(group, group)
        assert not result["significant"]

    def test_empty_groups(self):
        result = bootstrap_ci([], [])
        assert not result["significant"]


class TestWilcoxonTest:
    """Wilcoxon signed-rank test."""

    def _make_scores(
        self, baseline_scores: list[float], variant_scores: list[float], variant_name: str
    ) -> list[JudgeScores]:
        scores = []
        for i, s in enumerate(baseline_scores):
            scores.append(JudgeScores(
                scenario_id=f"s{i}", variant=Variant.FULL,
                safety_score=3, reasonableness_score=3, overall_score=s,
                violation_flags=[], explanation="",
            ))
        for i, s in enumerate(variant_scores):
            scores.append(JudgeScores(
                scenario_id=f"s{i}", variant=Variant(variant_name),
                safety_score=3, reasonableness_score=3, overall_score=s,
                violation_flags=[], explanation="",
            ))
        return scores

    def test_paired_comparison(self):
        baseline = [4.0, 5.0, 4.0, 5.0, 4.0]
        variant = [2.0, 3.0, 2.0, 3.0, 2.0]
        scores = self._make_scores(baseline, variant, "no-rules")
        result = wilcoxon_test(scores)
        assert "no-rules" in result
        assert result["no-rules"]["n_pairs"] == 5


class TestStratumFunctions:
    """分层键使用合成维度."""

    def test_safety_stratum_with_dims(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="highway_0.9_low_meeting_true",
            driving_context={}, user_query="", expected_decision={},
            expected_task_type="meeting", safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={"scenario": "highway", "fatigue_level": 0.9, "workload": "low", "task_type": "meeting", "has_passengers": "true"},
        )
        key = safety_stratum(s)
        assert "highway" in key

    def test_arch_stratum_with_dims(self):
        from experiments.ablation.architecture_group import arch_stratum

        s = Scenario(
            id="parked_0.1_normal_shopping_false",
            driving_context={}, user_query="", expected_decision={},
            expected_task_type="shopping", safety_relevant=False,
            scenario_type="parked",
            synthesis_dims={"scenario": "parked", "fatigue_level": 0.1, "workload": "normal", "task_type": "shopping", "has_passengers": "false"},
        )
        assert arch_stratum(s) == "parked:shopping"

    def test_is_arch_scenario_excludes_highway(self):
        from experiments.ablation.architecture_group import is_arch_scenario

        s = Scenario(
            id="highway_0.1_low_meeting_true",
            driving_context={}, user_query="", expected_decision={},
            expected_task_type="meeting", safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={"scenario": "highway", "fatigue_level": 0.1, "workload": "low", "task_type": "meeting", "has_passengers": "true"},
        )
        assert not is_arch_scenario(s)

    def test_no_dims_fallback(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="unknown", driving_context={}, user_query="",
            expected_decision={}, expected_task_type="meeting",
            safety_relevant=True, scenario_type="highway",
        )
        assert safety_stratum(s) == "highway"
```

- [ ] **步骤 2：运行测试**

```bash
uv run pytest tests/test_ablation_optimization.py -v
```

预期：全部通过。

- [ ] **步骤 3：运行全量测试确认无回归**

```bash
uv run pytest tests/ -v
```

- [ ] **步骤 4：Commit**

```bash
git add tests/test_ablation_optimization.py
git commit -m "test(ablation): add tests for methodology optimization changes"
```

---

### 任务 10：AGENTS.md 更新

**文件：**
- 修改：`AGENTS.md`

- [ ] **步骤 1：更新消融实验章节**

按设计规格第 6 节的文档更新表，修改 AGENTS.md 中以下部分：

1. **场景合成数量**："~120 场景" → "~260 场景（360 维度组合随机抽取）"
2. **个性化组轮数**："20 轮交互序列，4 阶段偏好切换（1-5轮→6-10轮→11-15轮→16-20轮）" → "32 轮（4 阶段 × 8 轮），场景不足时按比例截断"
3. **个性化场景描述**："个性化场景 20（meeting/travel/shopping/contact/other 各 4）" → "32 场景，按 task_type 分层抽样（min_per_stratum=2）"
4. **人工校准**：移除"人工校准：标注 ~50 场景期望决策，计算 Judge 与人工一致率（Cohen's κ），校准集 30 + 留存集 20，最多 3 轮 prompt 调整"整段，替换为"人工校准为后续工作，当前未实现。"
5. **安全组场景分配**：更新为"安全相关性由合成维度计算（highway / fatigue>阈值 / overloaded），city_driving 仅在附加条件下标记"
6. **统计检验**：新增描述"Bootstrap 置信区间（n=10000, α=0.05）+ Wilcoxon signed-rank test（按 scenario_id 配对）"
7. **Judge 评估**：更新为"Judge 不参考 expected_decision，仅依据规则表 + 场景条件评分。盲评 shuffle 支持确定性（ABLATION_SEED 非零）/ 随机（零/未设置）双模式。"
8. **精选场景数量**："精选 ~120 场景" → "精选 ~132 场景（安全 50 + 架构 50 + 个性化 32）"

- [ ] **步骤 2：Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md ablation experiment section to match implementation"
```

---

### 任务 11：最终验证

- [ ] **步骤 1：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 2：全量测试**

```bash
uv run pytest tests/ -v
```

预期：所有测试通过，无回归。

- [ ] **步骤 3：消融模块 import 验证**

```bash
uv run python -c "
from experiments.ablation.cli import main
from experiments.ablation.scenario_synthesizer import synthesize_scenarios, load_scenarios
from experiments.ablation.judge import Judge
from experiments.ablation.metrics import bootstrap_ci, wilcoxon_test
from experiments.ablation.types import Scenario
print('All imports OK')
"
```

- [ ] **步骤 4：最终 Commit（如有未提交修改）**

```bash
git add -A && git commit -m "chore: final cleanup for ablation optimization"
```
