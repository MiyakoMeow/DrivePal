# 知行车秘增强方案实现计划

> **面向 AI 代理的工作者：** 按任务顺序执行。每步标注 TDD（先测试后实现）。步骤使用 `- [ ]` 跟踪进度。

**目标：** 补六缺口 + 加四新能力——反馈学习、规则引擎数据驱动、概率推断、隐私保护、多用户全栈隔离、实验可视化。

**架构：** 全栈 per-user 目录隔离（`data/users/{user_id}/`）替代共享文件；嵌入向量相似度推断替代关键词 NB；7 条安全规则从 `config/rules.toml` 加载。

**技术栈：** Python 3.14, FastAPI + Strawberry GraphQL, FAISS, TOML, Chart.js CDN

**依赖顺序：** 任务 1（目录基建）→ 任务 2/3/4/5/6（独立模块）→ 任务 7（API 集成）→ 任务 8（工作流）→ 任务 9（文档）

---

### 任务 1：Per-user 目录基础设施

**覆盖规格：** §3.3 存储层 + 迁移，§3.3 config.py 改造

**文件：**
- 修改：`app/config.py`
- 修改：`app/storage/toml_store.py`
- 修改：`app/storage/jsonl_store.py`
- 修改：`app/storage/init_data.py`
- 修改：`tests/stores/test_toml_store.py`

**设计：**

`config.py` 改为提供 `user_data_dir(user_id: str) -> Path` 函数，而非全局 `DATA_DIR` 常量。存储层构造函数接受 `user_dir: Path` 替代旧的 `data_dir + filename` 组合。

```python
# app/config.py 新接口
DATA_ROOT = Path(os.getenv("DATA_DIR", "data"))

def user_data_dir(user_id: str = "default") -> Path:
    return DATA_ROOT / "users" / user_id
```

`TOMLStore.__init__()` 改为：
```python
def __init__(self, user_dir: Path, filename: str, default_factory=None):
    self.filepath = user_dir / filename  # 替换原来的 data_dir / filename
```

`JSONLinesStore.__init__()` 同理。

`init_storage()` 改为 `init_user_dir(user_id: str)`，创建完整目录结构。含迁移逻辑——检测 `data/*.jsonl` 存在则移至 `data/users/default/`。

- [ ] **步骤 1：编写 TOMLStore per-user 构造测试**

```python
# tests/stores/test_toml_store.py 追加
@pytest.mark.asyncio
async def test_toml_store_with_user_dir(tmp_path):
    """TOMLStore 使用 user_dir 构造，文件在 per-user 目录下。"""
    user_dir = tmp_path / "default"
    store = TOMLStore(user_dir=user_dir, filename="strategies.toml", default_factory=dict)
    await store.write({"key": "value"})
    assert (user_dir / "strategies.toml").exists()
    result = await store.read()
    assert result == {"key": "value"}

@pytest.mark.asyncio
async def test_toml_store_multiple_users_isolated(tmp_path):
    """两个用户的 TOMLStore 完全隔离。"""
    s1 = TOMLStore(user_dir=tmp_path / "alice", filename="prefs.toml", default_factory=dict)
    s2 = TOMLStore(user_dir=tmp_path / "bob", filename="prefs.toml", default_factory=dict)
    await s1.write({"theme": "dark"})
    await s2.write({"theme": "light"})
    r1 = await s1.read()
    r2 = await s2.read()
    assert r1 == {"theme": "dark"}
    assert r2 == {"theme": "light"}
```

- [ ] **步骤 2：运行测试验证失败**

`pytest tests/stores/test_toml_store.py::test_toml_store_with_user_dir -v` — 预期 FAIL，参数名不匹配

- [ ] **步骤 3：实现 TOMLStore 新构造函数**

```python
# app/storage/toml_store.py — 修改 __init__
def __init__(
    self,
    user_dir: Path | None = None,
    filename: str = "",
    default_factory: Callable[[], T] | None = None,
) -> None:
    if user_dir is not None:
        self.filepath = user_dir / filename
    else:
        # 兼容旧调用（如 AgentWorkflow 中的 strategies_store 旧写法）
        raise ValueError("user_dir is required; legacy data_dir+filename API removed")
    if default_factory is None:
        default_factory = cast("Callable[[], T]", dict)  # type: ignore[type-arg]
    self.default_factory = default_factory
    self._lock = _get_file_lock(self.filepath)
```

- [ ] **步骤 4：运行测试验证通过**

`pytest tests/stores/test_toml_store.py::test_toml_store_with_user_dir tests/stores/test_toml_store.py::test_toml_store_multiple_users_isolated -v`

- [ ] **步骤 5：实现 JSONLinesStore per-user 构造**

```python
# app/storage/jsonl_store.py — 修改 __init__
def __init__(self, user_dir: Path, filename: str) -> None:
    self.filepath = user_dir / filename
```

- [ ] **步骤 6：实现 config.py 新接口**

```python
# app/config.py
import os
from pathlib import Path

DATA_ROOT = Path(os.getenv("DATA_DIR", "data"))

def user_data_dir(user_id: str = "default") -> Path:
    return DATA_ROOT / "users" / user_id
```

- [ ] **步骤 7：实现 init_data.py 目录初始化与迁移**

```python
# app/storage/init_data.py — 重写 init_storage 为 init_user_dir + migrate
import shutil
from pathlib import Path
import tomli_w
from app.config import DATA_ROOT, user_data_dir

def _write_toml_data(filepath: Path, data: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("wb") as f:
        tomli_w.dump(data, f)

def _migrate_legacy() -> bool:
    """将平铺 data/*.jsonl 结构迁移至 data/users/default/。幂等。"""
    default_dir = user_data_dir("default")
    if default_dir.exists():
        return False  # 已迁移
    old_root = DATA_ROOT
    jsonl_files = ["events.jsonl", "interactions.jsonl", "feedback.jsonl", "experiment_results.jsonl"]
    toml_files = ["contexts.toml", "preferences.toml", "strategies.toml", "scenario_presets.toml"]
    legacy_files = jsonl_files + toml_files
    exists = any((old_root / f).exists() for f in legacy_files)
    if not exists:
        return False
    default_dir.mkdir(parents=True, exist_ok=True)
    for f in jsonl_files + toml_files:
        src = old_root / f
        if src.exists():
            shutil.move(str(src), str(default_dir / f))
    # 迁移 memorybank 子目录
    mb_dir = old_root / "memorybank"
    if mb_dir.exists():
        # 检测是否含 per-user 子目录（PR #120 结构）
        user_dirs = [d for d in mb_dir.iterdir() if d.is_dir() and d.name.startswith("user_")]
        if user_dirs:
            for ud in user_dirs:
                user_id = ud.name[5:]  # 去掉 "user_" 前缀
                target = user_data_dir(user_id) / "memorybank"
                if not target.exists():
                    shutil.move(str(ud), str(target))
        else:
            # 平铺结构 → 整体移至 default
            target = default_dir / "memorybank"
            if not target.exists():
                shutil.move(str(mb_dir), str(target))
    return True

def init_user_dir(user_id: str) -> Path:
    """初始化指定用户的完整目录结构。"""
    u_dir = user_data_dir(user_id)
    u_dir.mkdir(parents=True, exist_ok=True)

    jsonl_files = [
        "events.jsonl", "interactions.jsonl", "feedback.jsonl"
    ]
    for fname in jsonl_files:
        fp = u_dir / fname
        if not fp.exists():
            fp.write_text("", encoding="utf-8")

    dict_files = {
        "contexts.toml": {},
        "preferences.toml": {"language": "zh-CN"},
        "strategies.toml": {
            "preferred_time_offset": 15,
            "preferred_method": "visual",
            "reminder_weights": {},
            "ignored_patterns": [],
            "modified_keywords": [],
            "cooldown_periods": {},
        },
    }
    for fname, default_data in dict_files.items():
        fp = u_dir / fname
        if not fp.exists():
            _write_toml_data(fp, default_data)

    # scenario_presets 用 TOMLStore 列表格式
    sp_fp = u_dir / "scenario_presets.toml"
    if not sp_fp.exists():
        _write_toml_data(sp_fp, {"_list": []})

    return u_dir

def init_storage(data_dir: Path | None = None) -> None:
    """兼容旧调用——迁移+初始化默认用户。lifespan 使用。"""
    _migrate_legacy()
    init_user_dir("default")
```

- [ ] **步骤 8：编写 init_user_dir 单元测试**

```python
# tests/stores/test_toml_store.py — 追加
def test_init_user_dir_creates_all_files(tmp_path, monkeypatch):
    from app.storage.init_data import init_user_dir
    from app.config import user_data_dir
    # 重定向 DATA_ROOT 到 tmp_path
    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.config.user_data_dir", lambda uid: tmp_path / "users" / uid)
    u_dir = init_user_dir("testuser")
    assert u_dir.exists()
    assert (u_dir / "events.jsonl").exists()
    assert (u_dir / "strategies.toml").exists()
    assert (u_dir / "scenario_presets.toml").exists()

def test_migrate_legacy_moves_files(tmp_path, monkeypatch):
    from app.storage.init_data import _migrate_legacy
    # 创建旧平铺结构
    (tmp_path / "events.jsonl").write_text("")
    (tmp_path / "strategies.toml").write_text("")
    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.config.user_data_dir", lambda uid: tmp_path / "users" / uid)
    assert _migrate_legacy() is True
    assert (tmp_path / "users" / "default" / "events.jsonl").exists()
    assert not (tmp_path / "events.jsonl").exists()  # 已移走
```

- [ ] **步骤 9：运行现有测试确认无回归**

`pytest tests/stores/ -v` — 所有 TOML/JSONL 存储测试应通过

- [ ] **步骤 10：Commit**

```bash
git add app/config.py app/storage/toml_store.py app/storage/jsonl_store.py app/storage/init_data.py tests/stores/test_toml_store.py
git commit -m "feat: per-user directory isolation infrastructure

- TOMLStore/JSONLinesStore accept user_dir Path parameter
- add user_data_dir(user_id), DATA_ROOT in config.py
- init_user_dir creates full per-user directory tree
- migrate_legacy shards flat data/* into data/users/default/
- backward-compat: init_storage delegates to migrate+init_user_dir"
```

---

### 任务 2：数据驱动规则引擎

**覆盖规格：** §2.2

**文件：**
- 新增：`config/rules.toml`
- 重写：`app/agents/rules.py`
- 修改：`tests/test_rules.py`

**设计：**

`load_rules(path)` 读取 TOML，为每条规则构造 `Rule` 对象。条件字段解析为闭包，`apply_rules` 新增 `extra_channels` 合并逻辑。`SAFETY_RULES` 初始化为 `load_rules()` 结果（带 fallback）。

TOML 加载失败 → 回退 4 条硬编码默认规则 + 日志警告。

- [ ] **步骤 1：创建 config/rules.toml**

内容同规格文档 §2.2，7 条规则。

- [ ] **步骤 2：编写规则加载测试**

```python
# tests/test_rules.py — 修改 + 追加
def test_load_rules_from_toml(tmp_path):
    """从 TOML 文件加载 7 条规则。"""
    toml_path = tmp_path / "rules.toml"
    toml_path.write_text("""[[rules]]
name = "highway_audio_only"
scenario = "highway"
allowed_channels = ["audio"]
max_frequency_minutes = 30
priority = 10
""")
    rules = load_rules(toml_path)
    assert len(rules) == 1
    assert rules[0].name == "highway_audio_only"

def test_load_rules_fallback(tmp_path, caplog):
    """TOML 缺失时回退到 4 条默认规则并日志警告。"""
    rules = load_rules(tmp_path / "nonexistent.toml")
    assert len(rules) >= 4  # 4 条回退规则
    assert "fallback" in caplog.text.lower()

def test_city_driving_rule(tmp_path, rules_toml_7):  # fixture 提供完整 7 条 TOML
    """city_driving 场景匹配并限制 audio+15min。"""
    rules = load_rules(rules_toml_7)
    ctx = {"scenario": "city_driving"}
    result = apply_rules(ctx, rules)
    assert "audio" in result["allowed_channels"]
    assert result["max_frequency_minutes"] == 15

def test_passenger_extra_channels(tmp_path, rules_toml_7):
    """乘客在场 + city_driving → channels 含 visual（extra 追加）。"""
    rules = load_rules(rules_toml_7)
    ctx = {"scenario": "city_driving", "passengers": ["张三"]}
    result = apply_rules(ctx, rules)
    assert "visual" in result["allowed_channels"]
    assert "audio" in result["allowed_channels"]

def test_passenger_not_on_highway(tmp_path, rules_toml_7):
    """highway 场景排除乘客规则（not_scenario）。"""
    rules = load_rules(rules_toml_7)
    ctx = {"scenario": "highway"}
    matched = [r for r in rules if r.condition(ctx)]
    assert not any("passenger" in r.name for r in matched)

def test_not_scenario_missing_ctx(tmp_path, rules_toml_7):
    """scenario 缺失时 not_scenario 规则不触发。"""
    rules = load_rules(rules_toml_7)
    ctx = {}  # 无 scenario 字段
    matched = [r for r in rules if r.condition(ctx)]
    assert not any("passenger" in r.name for r in matched)

def test_max_frequency_merge_takes_min(tmp_path, rules_toml_7):
    """多规则含 max_frequency 时取最小值。"""
    rules = load_rules(rules_toml_7)
    # city_driving(max=15) + traffic_jam(max=10) 不会同时发生，但测试合并逻辑
    ctx = {"scenario": "traffic_jam"}
    # 额外加一条含 max_frequency 的规则
    extra_rule = Rule(name="test", condition=lambda c: True,
                       constraint={"max_frequency_minutes": 5}, priority=0)
    result = apply_rules(ctx, rules + [extra_rule])
    assert result["max_frequency_minutes"] == 5  # min(10, 5)
```

- [ ] **步骤 3：运行测试验证失败**

`pytest tests/test_rules.py::test_load_rules_from_toml -v`

- [ ] **步骤 4：实现 load_rules()**

```python
# app/agents/rules.py — 新增
import tomllib
from pathlib import Path

_FALLBACK_RULES: list[Rule] = [
    Rule(name="highway_audio_only",
         condition=lambda ctx: ctx.get("scenario") == "highway",
         constraint={"allowed_channels": ["audio"], "max_frequency_minutes": 30}, priority=10),
    Rule(name="fatigue_suppress",
         condition=lambda ctx: ctx.get("driver", {}).get("fatigue_level", 0) > _get_fatigue_threshold(),
         constraint={"only_urgent": True, "allowed_channels": ["audio"]}, priority=20),
    Rule(name="overloaded_postpone",
         condition=lambda ctx: ctx.get("driver", {}).get("workload", "") == "overloaded",
         constraint={"postpone": True}, priority=15),
    Rule(name="parked_all_channels",
         condition=lambda ctx: ctx.get("scenario") == "parked",
         constraint={"allowed_channels": ["visual", "audio", "detailed"]}, priority=5),
]

def _build_condition(rule_cfg: dict) -> Callable[[dict], bool]:
    """从 TOML 配置项构造 Rule.condition 闭包。各条件 AND 组合。"""
    checks: list[Callable[[dict], bool]] = []

    if "scenario" in rule_cfg:
        val = rule_cfg["scenario"]
        checks.append(lambda ctx, v=val: ctx.get("scenario") == v)  # 默认参数捕获当前值

    if "not_scenario" in rule_cfg:
        val = rule_cfg["not_scenario"]
        checks.append(lambda ctx, v=val: bool(ctx.get("scenario")) and ctx.get("scenario") != v)

    if "workload" in rule_cfg:
        val = rule_cfg["workload"]
        checks.append(lambda ctx, v=val: ctx.get("driver", {}).get("workload") == v)

    if "fatigue_above" in rule_cfg:
        threshold = rule_cfg["fatigue_above"]
        checks.append(lambda ctx, t=threshold: ctx.get("driver", {}).get("fatigue_level", 0) > t)

    if "has_passengers" in rule_cfg:
        checks.append(lambda ctx: bool(ctx.get("passengers")))

    def condition(ctx: dict) -> bool:
        return all(check(ctx) for check in checks) if checks else False

    return condition

def load_rules(path: Path) -> list[Rule]:
    """从 TOML 文件加载规则列表。失败时回退到默认规则。"""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as e:
        logger.warning("Failed to load rules from %s: %s, using fallback", path, e)
        return list(_FALLBACK_RULES)

    raw_rules = data.get("rules", [])
    if not raw_rules:
        logger.warning("No rules found in %s, using fallback", path)
        return list(_FALLBACK_RULES)

    rules: list[Rule] = []
    for cfg in raw_rules:
        r = Rule(
            name=cfg["name"],
            condition=_build_condition(cfg),
            constraint={k: v for k, v in cfg.items() if k not in ("name", "priority", "scenario", "not_scenario", "workload", "fatigue_above", "has_passengers")},
            priority=cfg.get("priority", 0),
        )
        rules.append(r)
    return rules

# 模块加载时初始化
_RULES_PATH = Path("config/rules.toml")
SAFETY_RULES: list[Rule] = load_rules(_RULES_PATH)
```

- [ ] **步骤 5：修改 apply_rules 支持 extra_channels**

```python
# app/agents/rules.py — apply_rules() 末尾追加
# 在 dict_result 构建后（line 115 region），增加 extra_channels 处理
    # 收集 extra_channels 并追加到 merged_channels
    extra = set()
    for r in matched:
        ec = r.constraint.get("extra_channels", [])
        if isinstance(ec, list):
            extra.update(ec)
    if extra:
        merged_channels = list(set(merged_channels + sorted(extra)))
```

- [ ] **步骤 6：运行所有规则测试**

`pytest tests/test_rules.py -v` — 全部通过

- [ ] **步骤 7：Commit**

```bash
git add config/rules.toml app/agents/rules.py tests/test_rules.py
git commit -m "feat: data-driven rules engine with 7 safety rules

- load_rules() reads config/rules.toml, builds Rule objects
- fallback to 4 hardcoded defaults on load failure
- add extra_channels merge logic: append after intersection
- add city_driving, traffic_jam, passenger_present rules
- not_scenario only evaluates when scenario field present"
```

---

### 任务 3：反馈学习恢复

**覆盖规格：** §2.1

**文件：**
- 修改：`app/memory/memory_bank/store.py`（`update_feedback` 记录 feedback）
- 修改：`app/api/resolvers/mutation.py`（`submit_feedback` 加权重更新）
- 修改：`tests/stores/test_memory_bank_store.py`
- 新增：`tests/test_mutation_feedback.py`

**设计：**

`store.update_feedback()` 记录 feedback 到 per-user `feedback.jsonl`（通过 JSONLinesStore）。`submit_feedback` resolver 同时：
1. 调用 `store.update_feedback()` 记录
2. 打开 `data/users/{currentUser}/strategies.toml` 更新 `reminder_weights`

初始权重 0.5，accept +0.1（上限 1.0），ignore -0.1（下限 0.1）。

- [ ] **步骤 1：编写 feedback 记录测试**

```python
# tests/stores/test_memory_bank_store.py — 追加
@pytest.mark.asyncio
async def test_update_feedback_records_feedback(store_with_mock_embedding, tmp_path):
    """update_feedback 写入 feedback.jsonl。"""
    fb = FeedbackData(action="accept", type="meeting", modified_content=None)
    await store_with_mock_embedding.update_feedback("evt-1", fb)
    # 验证 feedback.jsonl 有记录
    feedback_path = store_with_mock_embedding._user_dir / "feedback.jsonl"
    # (需要 store 暴露 _user_dir 或通过 fixture 传入)
```

- [ ] **步骤 2：实现 store.update_feedback 记录逻辑**

先确保 `MemoryBankStore.__init__()` 保存 `self._user_dir`：

```python
# app/memory/memory_bank/store.py — __init__ 中追加
    self._user_dir = data_dir  # data_dir 即为 data/users/{id}/，非 memorybank 子目录
```

然后实现 `update_feedback`：

```python
# app/memory/memory_bank/store.py — update_feedback 替换 pass
async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
    """记录用户反馈到 feedback.jsonl。不修改事件 memory_strength。"""
    record = {
        "event_id": event_id,
        "action": feedback.action,
        "type": feedback.type,
        "modified_content": feedback.modified_content,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    from app.storage.jsonl_store import JSONLinesStore  # 延迟导入
    fb_store = JSONLinesStore(user_dir=self._user_dir, filename="feedback.jsonl")
    await fb_store.append(record)
    logger.info("Feedback recorded: event_id=%s action=%s", event_id, feedback.action)
```

需在 `MemoryBankStore.__init__()` 中保存 `self._user_dir = data_dir`（即构造时传入的 user 目录路径，而非 memorybank 子目录）。当前 `__init__` 中 `user_dir = data_dir` 即为 `data/users/{id}/`，`_index` 等存于 `user_dir / "memorybank"` 子目录。

- [ ] **步骤 3：编写权重更新测试**

```python
# tests/test_mutation_feedback.py — 新文件
import pytest
from app.storage.toml_store import TOMLStore

@pytest.mark.asyncio
async def test_accept_increases_weight(tmp_path):
    """accept → 权重 +0.1，初始 0.5 变为 0.6。"""
    store = TOMLStore(user_dir=tmp_path, filename="strategies.toml", default_factory=dict)
    await store.write({"reminder_weights": {"meeting": 0.5}})
    # 执行 accept 逻辑（模拟 resolver 层）
    current = await store.read()
    weights = current.get("reminder_weights", {})
    etype = "meeting"
    weights[etype] = min(weights.get(etype, 0.5) + 0.1, 1.0)
    current["reminder_weights"] = weights
    await store.update("reminder_weights", weights)
    result = await store.read()
    assert result["reminder_weights"]["meeting"] == 0.6

@pytest.mark.asyncio
async def test_ignore_decreases_weight(tmp_path):
    """ignore → 权重 -0.1，下限 0.1。"""
    store = TOMLStore(user_dir=tmp_path, filename="strategies.toml", default_factory=dict)
    await store.write({"reminder_weights": {"meeting": 0.2}})
    current = await store.read()
    weights = current.get("reminder_weights", {})
    weights["meeting"] = max(weights.get("meeting", 0.5) - 0.1, 0.1)
    current["reminder_weights"] = weights
    await store.update("reminder_weights", weights)
    result = await store.read()
    assert result["reminder_weights"]["meeting"] == 0.1

@pytest.mark.asyncio
async def test_new_type_default_weight(tmp_path):
    """不存在的事件类型初始权重 0.5。"""
    store = TOMLStore(user_dir=tmp_path, filename="strategies.toml", default_factory=dict)
    await store.write({"reminder_weights": {}})
    current = await store.read()
    weights = current.get("reminder_weights", {})
    etype = "shopping"
    weights[etype] = min(weights.get(etype, 0.5) + 0.1, 1.0)
    assert weights["shopping"] == 0.6
```

- [ ] **步骤 4：实现 mutation resolver 权重更新**

```python
# app/api/resolvers/mutation.py — submit_feedback 方法内，在 store.update_feedback 后追加
    # 2.1 反馈权重更新
    from app.storage.toml_store import TOMLStore
    from app.config import user_data_dir

    # 获取事件类型（submit_feedback 已在前面通过 mm.get_event_type 拿到，存在变量 actual_type）
    user_dir = user_data_dir(current_user)  # current_user 从 input 获取
    strategy_store = TOMLStore(user_dir=user_dir, filename="strategies.toml", default_factory=dict)
    current_strategy = await strategy_store.read()
    weights = current_strategy.get("reminder_weights", {})
    delta = 0.1 if safe_action == "accept" else -0.1
    new_weight = weights.get(actual_type, 0.5) + delta
    weights[actual_type] = max(0.1, min(1.0, new_weight))
    await strategy_store.update("reminder_weights", weights)
```

- [ ] **步骤 5：运行测试**

`pytest tests/test_mutation_feedback.py tests/stores/test_memory_bank_store.py -v`

- [ ] **步骤 6：Commit**

```bash
git add app/memory/memory_bank/store.py app/api/resolvers/mutation.py tests/stores/test_memory_bank_store.py tests/test_mutation_feedback.py
git commit -m "feat: feedback learning with per-user weight updates

- store.update_feedback records to feedback.jsonl
- submit_feedback resolver updates reminder_weights in strategies.toml
- accept +0.1 (max 1.0), ignore -0.1 (min 0.1), default 0.5"
```

---

### 任务 4：概率推断模块

**覆盖规格：** §3.1

**文件：**
- 新增：`app/agents/probabilistic.py`
- 新增：`tests/test_probabilistic.py`

**设计：**

`infer_intent(query_text, memory_store) -> dict` 调用 `store.search(query_text, top_k=20)` → 按 type 聚合 score → 归一化。`compute_interrupt_risk(ctx) -> float` 加权公式。环境变量 `PROBABILISTIC_INFERENCE_ENABLED` 控制开关。

冷启动：检索结果空 → 所有 type 等概率。

- [ ] **步骤 1：编写意图推断测试**

```python
# tests/test_probabilistic.py — 新文件
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.probabilistic import infer_intent, compute_interrupt_risk
from app.memory.schemas import SearchResult

def make_search_result(event_type: str, score: float) -> SearchResult:
    """构造 SearchResult mock。"""
    event = {"type": event_type, "content": "test"}
    return SearchResult(event=event, score=score, interactions=[])

class MockStore:
    async def search(self, query: str, top_k: int = 20):
        return self._results
    def set_results(self, results):
        self._results = results

@pytest.mark.asyncio
async def test_infer_intent_aggregates_by_type():
    """多个同 type 事件的 score 聚合。"""
    store = MockStore()
    store.set_results([
        make_search_result("meeting", 0.8),
        make_search_result("meeting", 0.6),
        make_search_result("travel", 0.4),
    ])
    result = await infer_intent("明天开会", store)
    assert result["intent_confidence"] > result["alt_confidence"]
    assert result["alternative"] is not None

@pytest.mark.asyncio
async def test_cold_start_uniform():
    """检索无结果时所有 type 等概率。"""
    store = MockStore()
    store.set_results([])
    result = await infer_intent("明天开会", store)
    assert result["intent_confidence"] == pytest.approx(0.2, abs=0.1)  # 5 types 等概率

def test_interrupt_risk_calculation():
    """打断风险加权公式计算。"""
    ctx = {
        "driver": {"fatigue_level": 0.7, "workload": "normal"},
        "scenario": "city_driving",
        "spatial": {"current_location": {"speed_kmh": 50}},
    }
    risk = compute_interrupt_risk(ctx)
    assert 0.0 <= risk <= 1.0
    # 0.4*0.7 + 0.3*0.3 + 0.2*0.4 + 0.1*0.5 = 0.28+0.09+0.08+0.05 = 0.50
    assert risk == pytest.approx(0.50, abs=0.01)

def test_interrupt_risk_scenario_none_fallback():
    """scenario 缺失时 scenario_risk 取 0.5。"""
    ctx = {"driver": {"fatigue_level": 0.5, "workload": "low"}}
    risk = compute_interrupt_risk(ctx)
    # 0.4*0.5 + 0.3*0.1 + 0.2*0.5 + 0.1*0.0 = 0.20+0.03+0.10+0.00 = 0.33
    assert risk == pytest.approx(0.33, abs=0.01)
```

- [ ] **步骤 2：运行测试验证失败**

`pytest tests/test_probabilistic.py -v`

- [ ] **步骤 3：实现 probabilistic.py**

```python
# app/agents/probabilistic.py
"""概率推断模块：意图不确定性 + 打断风险评估。"""
import logging
import os
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_WORKLOAD_MAP = {"low": 0.1, "normal": 0.3, "high": 0.6, "overloaded": 0.9}
_SCENARIO_MAP = {"parked": 0.0, "city_driving": 0.4, "traffic_jam": 0.3, "highway": 0.7}

def _speed_factor(speed_kmh: float) -> float:
    if speed_kmh <= 0: return 0.0
    if speed_kmh <= 40: return 0.3
    if speed_kmh <= 80: return 0.5
    return 0.8

def is_enabled() -> bool:
    return os.environ.get("PROBABILISTIC_INFERENCE_ENABLED", "1") != "0"

async def infer_intent(query_text: str, memory_store: Any) -> dict:
    """从 MemoryBank 检索相似事件，聚合 type 得分推断意图。"""
    try:
        results = await memory_store.search(query_text, top_k=20)
    except Exception as e:
        logger.warning("Intent inference search failed: %s", e)
        results = []

    if not results:
        return {"intent_confidence": 0.2, "alternative": None, "alt_confidence": 0.0}

    type_scores: dict[str, float] = defaultdict(float)
    for r in results:
        etype = r.event.get("type", "general") if isinstance(r.event, dict) else getattr(r.event, "type", "general")
        type_scores[etype] += max(r.score, 0.0)

    total = sum(type_scores.values()) or 1.0
    confidences = {t: s / total for t, s in type_scores.items()}
    sorted_types = sorted(confidences.items(), key=lambda x: x[1], reverse=True)

    return {
        "intent_confidence": sorted_types[0][1],
        "alternative": sorted_types[1][0] if len(sorted_types) > 1 else None,
        "alt_confidence": sorted_types[1][1] if len(sorted_types) > 1 else 0.0,
    }

def compute_interrupt_risk(driving_context: dict) -> float:
    """根据驾车状态计算打断风险 0~1。"""
    driver = driving_context.get("driver", {})
    fatigue = float(driver.get("fatigue_level", 0.0))
    workload = driver.get("workload", "normal")
    scenario = driving_context.get("scenario")

    w_score = _WORKLOAD_MAP.get(workload, 0.3)
    s_risk = _SCENARIO_MAP.get(scenario, 0.5) if scenario else 0.5
    speed = driving_context.get("spatial", {}).get("current_location", {}).get("speed_kmh", 0.0)
    speed = float(speed) if speed is not None else 0.0
    sf = _speed_factor(speed)

    risk = 0.4 * fatigue + 0.3 * w_score + 0.2 * s_risk + 0.1 * sf
    if w_score >= 0.9 and risk >= 0.36:
        logger.info("High interrupt risk (%.2f) with overloaded workload — warning marker appended", risk)

    return min(max(risk, 0.0), 1.0)
```

- [ ] **步骤 4：运行测试验证通过**

`pytest tests/test_probabilistic.py -v`

- [ ] **步骤 5：Commit**

```bash
git add app/agents/probabilistic.py tests/test_probabilistic.py
git commit -m "feat: probabilistic inference — embedding-based intent + interrupt risk

- infer_intent: MemoryBankStore.search → aggregate type scores → normalize
- compute_interrupt_risk: weighted formula from DrivingContext fields
- cold start: no results → uniform distribution
- env var PROBABILISTIC_INFERENCE_ENABLED toggle
- scenario=None fallback: scenario_risk=0.5"
```

---

### 任务 5：隐私保护模块

**覆盖规格：** §3.2

**文件：**
- 新增：`app/memory/privacy.py`
- 新增：`tests/test_privacy.py`

**设计：**

`sanitize_location(lat, lon, address) -> tuple` 截断经纬度至 2 位小数，地址取街道级（逗号前第一段）。

- [ ] **步骤 1：编写测试**

```python
# tests/test_privacy.py
from app.memory.privacy import sanitize_location, sanitize_context

def test_latitude_truncated():
    lat, _, _ = sanitize_location(31.230416, 121.473701, "上海市浦东新区世纪大道100号")
    assert lat == 31.23

def test_longitude_truncated():
    _, lon, _ = sanitize_location(31.230416, 121.473701, "")
    assert lon == 121.47

def test_address_street_level():
    _, _, addr = sanitize_location(0, 0, "北京市海淀区中关村大街1号, 创新大厦")
    assert "海淀区" in addr  # 保留街道级，去掉详细门牌号

def test_address_no_comma_preserved():
    _, _, addr = sanitize_location(0, 0, "上海市浦东新区")
    assert addr == "上海市浦东新区"

def test_sanitize_context_handles_none_driver():
    """无 driver 字段的 context 不影响。"""
    assert sanitize_context({}) == {}
```

- [ ] **步骤 2：实现 privacy.py**

```python
# app/memory/privacy.py
"""隐私保护工具：位置脱敏。"""

def sanitize_location(latitude: float, longitude: float, address: str) -> tuple[float, float, str]:
    """经纬度截断至 2 位小数（~1km），地址取街道级。"""
    lat = round(latitude, 2)
    lon = round(longitude, 2)
    # 地址取逗号或中文顿号前第一段
    for sep in (",", "，", "、"):
        if sep in address:
            address = address.split(sep)[0].strip()
            break
    return lat, lon, address

def sanitize_context(context: dict) -> dict:
    """递归脱敏 context 中的位置信息。"""
    result = dict(context)
    spatial = result.get("spatial", {})
    if isinstance(spatial, dict):
        loc = spatial.get("current_location")
        if isinstance(loc, dict):
            lat, lon, addr = sanitize_location(
                float(loc.get("latitude", 0)),
                float(loc.get("longitude", 0)),
                str(loc.get("address", "")),
            )
            loc["latitude"] = lat
            loc["longitude"] = lon
            loc["address"] = addr
        dest = spatial.get("destination")
        if isinstance(dest, dict):
            dlat, dlon, daddr = sanitize_location(
                float(dest.get("latitude", 0)),
                float(dest.get("longitude", 0)),
                str(dest.get("address", "")),
            )
            dest["latitude"] = dlat
            dest["longitude"] = dlon
            dest["address"] = daddr
    return result
```

- [ ] **步骤 3：运行测试**

`pytest tests/test_privacy.py -v`

- [ ] **步骤 4：Commit**

```bash
git add app/memory/privacy.py tests/test_privacy.py
git commit -m "feat: privacy module — location sanitization

- sanitize_location truncates lat/lon to 2 decimal places
- address stripped to street level (first comma segment)
- sanitize_context recursively sanitizes spatial fields"
```

---

### 任务 6：实验数据可视化

**覆盖规格：** §3.4

**文件：**
- 新增：`app/storage/experiment_store.py`
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/query.py`
- 修改：`webui/index.html`
- 修改：`webui/app.js`
- 新增：`tests/test_experiment_results.py`

**设计：**

`experiment_store.py` 只读模块，读取 `data/experiment_benchmark.toml`。GraphQL 返回 `ExperimentResults`。WebUI 新增标签页用 Chart.js 柱状图。

- [ ] **步骤 1：创建 experiment_store.py**

```python
# app/storage/experiment_store.py
"""实验基准数据只读存储。"""
import tomllib
from pathlib import Path

from app.config import DATA_ROOT

_BENCHMARK_FILE = DATA_ROOT / "experiment_benchmark.toml"

def read_benchmark() -> dict:
    """读取 experiment_benchmark.toml，不存在返回空。"""
    if not _BENCHMARK_FILE.exists():
        return {}
    with _BENCHMARK_FILE.open("rb") as f:
        return tomllib.load(f)
```

- [ ] **步骤 2：新增 GraphQL 类型**

```python
# app/api/graphql_schema.py — 追加
@strawberry.type
class ExperimentResult:
    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float

@strawberry.type
class ExperimentResults:
    strategies: list[ExperimentResult]
```

- [ ] **步骤 3：新增 query resolver**

```python
# app/api/resolvers/query.py — Query 类追加
    @strawberry.field
    async def experiment_results(self) -> ExperimentResults:
        data = read_benchmark()
        strategies = []
        for name, metrics in data.get("strategies", {}).items():
            strategies.append(ExperimentResult(
                strategy=name,
                exact_match=metrics.get("exact_match", 0.0),
                field_f1=metrics.get("field_f1", 0.0),
                value_f1=metrics.get("value_f1", 0.0),
            ))
        return ExperimentResults(strategies=strategies)
```

- [ ] **步骤 4：WebUI 图表 — app.js 追加**

```javascript
// webui/app.js — 追加实验结果标签页和图表绘制
function showExperimentTab() {
    fetch('/graphql', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query: '{experimentResults{strategies{strategy exact_match field_f1 value_f1}}}'})
    })
    .then(r => r.json())
    .then(data => {
        const strats = data.data.experimentResults.strategies;
        const labels = strats.map(s => s.strategy);
        const exact = strats.map(s => s.exact_match);
        const field = strats.map(s => s.field_f1);
        const value = strats.map(s => s.value_f1);
        drawChart(labels, exact, field, value);
    });
}

function drawChart(labels, exact, field, value) {
    const ctx = document.getElementById('experimentChart').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {label: 'Exact Match', data: exact, backgroundColor: '#4285F4'},
                {label: 'Field F1', data: field, backgroundColor: '#34A853'},
                {label: 'Value F1', data: value, backgroundColor: '#FBBC05'},
            ]
        },
        options: {
            responsive: true,
            plugins: {
                title: {display: true, text: '五策略对比'},
            }
        }
    });
}
```

- [ ] **步骤 5：WebUI HTML — 追加标签页和 canvas**

在 `index.html` 中添加实验结果标签按钮和 `<canvas id="experimentChart">`，加载 Chart.js CDN。

- [ ] **步骤 6：编写测试**

```python
# tests/test_experiment_results.py
import pytest
import tomli_w
from app.storage.experiment_store import read_benchmark

def test_read_benchmark_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.experiment_store._BENCHMARK_FILE", tmp_path / "nonexistent.toml")
    assert read_benchmark() == {}

def test_read_benchmark_parses(tmp_path, monkeypatch):
    """读取五策略对比数据。"""
    data = {"strategies": {"memory_bank": {"exact_match": 0.5, "field_f1": 0.7, "value_f1": 0.6}}}
    fp = tmp_path / "experiment_benchmark.toml"
    with fp.open("wb") as f:
        tomli_w.dump(data, f)
    monkeypatch.setattr("app.storage.experiment_store._BENCHMARK_FILE", fp)
    result = read_benchmark()
    assert result["strategies"]["memory_bank"]["exact_match"] == 0.5
```

- [ ] **步骤 7：运行测试**

`pytest tests/test_experiment_results.py -v`

- [ ] **步骤 8：Commit**

```bash
git add app/storage/experiment_store.py app/api/graphql_schema.py app/api/resolvers/query.py webui/index.html webui/app.js tests/test_experiment_results.py
git commit -m "feat: experiment result visualization

- experiment_store.py reads experiment_benchmark.toml (read-only)
- GraphQL experimentResults query returns 5-strategy comparison
- WebUI bar chart with Chart.js — Exact Match / Field F1 / Value F1"
```

---

### 任务 7：多用户 API 层集成

**覆盖规格：** §3.3 API 层 + §3.2 导出/删除 mutation + §3.3 DrivingContext 扩展

**文件：**
- 修改：`app/schemas/context.py`
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/mutation.py`
- 修改：`app/api/resolvers/query.py`
- 修改：`app/api/resolvers/converters.py`
- 新增：`tests/test_multi_user.py`

**设计：**

所有 Input type 加 `currentUser: str = "default"`。所有 query/mutation 根据 `currentUser` 路由到 `data/users/{currentUser}/`。`DrivingContext` 加 `passengers` 字段。新增 `exportData`、`deleteAllData` mutation。

- [ ] **步骤 1：DrivingContext 加 passengers 字段**

```python
# app/schemas/context.py
class DrivingContext(BaseModel):
    driver: DriverState = Field(default_factory=DriverState)
    spatial: SpatioTemporalContext = Field(default_factory=SpatioTemporalContext)
    traffic: TrafficCondition = Field(default_factory=TrafficCondition)
    scenario: Literal["parked", "city_driving", "highway", "traffic_jam"] = "parked"
    passengers: list[str] = Field(default_factory=list)  # 新增
```

- [ ] **步骤 2：GraphQL schema 加 currentUser + exportData/deleteAllData 类型**

```python
# app/api/graphql_schema.py — 现有 Input 追加 current_user + 新增导出/删除类型
@strawberry.input
class ProcessQueryInput:
    query: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    context: DrivingContextInput | None = None
    current_user: str = "default"  # 新增

@strawberry.input
class FeedbackInput:
    event_id: str
    action: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    modified_content: str | None = None
    current_user: str = "default"  # 新增

# DrivingContextInput + DrivingContextGQL 追加 passengers
@strawberry.input
class DrivingContextInput:
    driver: DriverStateInput | None = None
    # ... existing fields ...
    passengers: list[str] = strawberry.field(default_factory=list)  # 新增

# 同时修改 DrivingContextGQL（输出类型——pydantic_type 自动映射，但需显式声明）
@pydantic_type(_DrivingContext)
class DrivingContextGQL:
    driver: auto
    spatial: auto
    traffic: auto
    scenario: str
    passengers: auto  # 新增

# 新增导出/删除类型
@strawberry.type
class ExportDataResult:
    files: JSON

@strawberry.input
class DeleteDataInput:
    current_user: str
```

- [ ] **步骤 3：converters.py 加 per-user preset_store（需在步骤 4 前完成）**

```python
# app/api/resolvers/converters.py
def preset_store(current_user: str = "default") -> TOMLStore:
    from app.config import user_data_dir
    return TOMLStore(user_dir=user_data_dir(current_user), filename="scenario_presets.toml", default_factory=list)
```

- [ ] **步骤 4：query resolver 加 currentUser**

```python
# app/api/resolvers/query.py
@strawberry.field
async def history(self, limit: int = 10, memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK,
                   current_user: str = "default") -> list[MemoryEventGQL]:
    mm = get_memory_module()
    mode = MemoryMode(memory_mode.value)
    events = await mm.get_history(limit=limit, mode=mode, user_id=current_user)
    ...

@strawberry.field
async def scenario_presets(self, current_user: str = "default") -> list[ScenarioPresetGQL]:
    store = preset_store(current_user)
    ...
```

- [ ] **步骤 5：mutation resolver 加 currentUser + exportData/deleteAllData**

```python
# app/api/resolvers/mutation.py — 现有 mutation 追加 current_user 参数
    @strawberry.mutation
    async def save_scenario_preset(self, preset_input: ScenarioPresetInput,
                                    current_user: str = "default") -> ScenarioPresetGQL:
        store = preset_store(current_user)
        ...

    @strawberry.mutation
    async def delete_scenario_preset(self, preset_id: str,
                                      current_user: str = "default") -> bool:
        store = preset_store(current_user)
        ...

    # 新增导出/删除 mutation
    @strawberry.mutation
    async def export_data(self, current_user: str) -> ExportDataResult:
        """导出当前用户全量文本数据。"""
        import json
        from pathlib import Path
        u_dir = user_data_dir(current_user)
        files = {}
        for fpath in u_dir.rglob("*"):
            if fpath.is_file() and fpath.suffix in (".jsonl", ".toml", ".json"):
                try:
                    content = fpath.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                rel = str(fpath.relative_to(u_dir))
                files[rel] = content
        return ExportDataResult(files=files)

    @strawberry.mutation
    async def delete_all_data(self, current_user: str) -> bool:
        """删除当前用户全量数据。"""
        import shutil
        u_dir = user_data_dir(current_user)
        if u_dir.exists():
            shutil.rmtree(u_dir)
        return True
```

- [ ] **步骤 6：MemoryModule 加 user_id 参数透传**

```python
# app/memory/memory.py — get_history/search/write_interaction 加 user_id
# app/memory/singleton.py — get_memory_module 返回已含 user_id 路由
# （MemoryBank 底层已有 get_store(user_id)，现在上层透传）
```

- [ ] **步骤 7：编写多用户隔离集成测试**

```python
# tests/test_multi_user.py
@pytest.mark.asyncio
async def test_users_data_isolated(tmp_path):
    """两个用户各自写入，读取互不干扰。"""
    init_user_dir("alice")
    init_user_dir("bob")
    # Alice 写 event
    store_a = JSONLinesStore(user_dir=user_data_dir("alice"), filename="events.jsonl")
    await store_a.append({"event": "alice_test"})
    # Bob 写 event
    store_b = JSONLinesStore(user_dir=user_data_dir("bob"), filename="events.jsonl")
    await store_b.append({"event": "bob_test"})
    # Alice 读只有自己的
    events_a = await store_a.read_all()
    events_b = await store_b.read_all()
    assert len(events_a) == 1 and events_a[0]["event"] == "alice_test"
    assert len(events_b) == 1 and events_b[0]["event"] == "bob_test"
```

- [ ] **步骤 8：运行测试**

`pytest tests/test_multi_user.py -v`

- [ ] **步骤 9：Commit**

```bash
git add app/schemas/context.py app/api/graphql_schema.py app/api/resolvers/mutation.py app/api/resolvers/query.py app/api/resolvers/converters.py app/memory/memory.py tests/test_multi_user.py
git commit -m "feat: multi-user API layer — currentUser routing + export/delete

- all Input types add current_user field (default 'default')
- query history/scenarioPresets route to per-user data dir
- mutation exportData serializes user dir, deleteAllData rmtree
- DrivingContext.passengers field for passenger rule
- preset_store per-user, converters accept current_user"
```

---

### 任务 8：工作流集成

**覆盖规格：** §2.2 频次约束 + §3.1 概率推断接入 + §3.3 per-user 传递

**文件：**
- 修改：`app/agents/workflow.py`
- 修改：`app/api/resolvers/mutation.py`（processQuery 传 currentUser）

**设计：**

`AgentWorkflow.__init__` 加 `current_user` 参数，透传到 `MemoryModule`、`TOMLStore`。`_strategy_node` 调用 `infer_intent()` + `compute_interrupt_risk()` 拼入 prompt。`_execution_node` 加频次约束检查（查询最近一次提醒时间，间隔 < `max_frequency_minutes` 则抑制）。

- [ ] **步骤 1：修改 workflow.py 构造函数**

```python
# app/agents/workflow.py — __init__ 加 current_user
def __init__(self, data_dir: Path = Path("data"), memory_mode=..., memory_module=None,
             current_user: str = "default"):
    self.current_user = current_user
    user_dir = data_dir / "users" / current_user
    self._strategies_store = TOMLStore(user_dir=user_dir, filename="strategies.toml", default_factory=dict)
    # ... 其余不变
```

- [ ] **步骤 1b：_execution_node 写入前调用隐私脱敏**

```python
# app/agents/workflow.py — _execution_node 中，write_interaction 前对 driving_ctx 脱敏
    from app.memory.privacy import sanitize_context
    if driving_ctx:
        driving_ctx = sanitize_context(driving_ctx)
```

- [ ] **步骤 2：_strategy_node 接入概率推断**

```python
# app/agents/workflow.py — _strategy_node 开头加
    from app.agents.probabilistic import infer_intent, compute_interrupt_risk, is_enabled

    prob_text = ""
    if is_enabled() and self._memory_mode == MemoryMode.MEMORY_BANK:
        intent = await infer_intent(state.get("original_query", ""), self.memory_module)
        risk = compute_interrupt_risk(driving_context or {})
        intent["interrupt_risk"] = round(risk, 2)
        prob_text = f"\n\n概率推断: {json.dumps(intent, ensure_ascii=False)}"
        if risk >= 0.36:
            prob_text += "\n⚠ 当前打断风险较高，请谨慎决定"

    # 读取 reminder_weights 注入 prompt——偏好高权重类型
    strategies_data = await self._strategies_store.read()
    weights = strategies_data.get("reminder_weights", {})
    weights_text = ""
    if weights:
        weights_text = f"\n\n事件类型偏好权重: {json.dumps(weights, ensure_ascii=False)}"
        weights_text += "\n权重越高表示用户偏好该类型提醒，请在决策时优先考虑高权重类型。"

    prompt = f"""{SYSTEM_PROMPTS["strategy"]}
...
{weights_text}{prob_text}
..."""
```

- [ ] **步骤 3：_execution_node 加频次约束**

```python
# app/agents/workflow.py — _execution_node 在 postpone 检查后追加
    # 频次约束检查
    constraints = apply_rules(driving_ctx) if driving_ctx else {}
    max_freq = constraints.get("max_frequency_minutes")
    if max_freq is not None:
        recent_events = await self._safe_memory_history()
        now = datetime.now(UTC)
        for evt in recent_events:
            evt_time_str = evt.get("created_at", "")
            if not evt_time_str:
                continue
            try:
                evt_time = datetime.fromisoformat(evt_time_str)
            except (ValueError, TypeError):
                continue
            delta_minutes = (now - evt_time).total_seconds() / 60.0
            if delta_minutes < max_freq:
                result = f"提醒已抑制：距上次提醒仅 {delta_minutes:.0f} 分钟（限制 {max_freq} 分钟）"
                if stages is not None:
                    stages.execution = {
                        "content": None, "event_id": None, "result": result,
                    }
                return {"result": result, "event_id": None}
```

- [ ] **步骤 4：mutation resolver 传 currentUser**

```python
# app/api/resolvers/mutation.py — process_query 修改
    workflow = AgentWorkflow(
        data_dir=DATA_ROOT,
        memory_mode=MemoryMode(query_input.memory_mode.value),
        memory_module=mm,
        current_user=query_input.current_user,
    )
```

- [ ] **步骤 5：运行现有测试确认无回归**

`pytest tests/ -v --ignore=tests/test_graphql.py`（排除需完整服务的 GraphQL 测试）

- [ ] **步骤 6：Commit**

```bash
git add app/agents/workflow.py app/api/resolvers/mutation.py
git commit -m "feat: workflow integration — probabilistic inference + frequency guard

- AgentWorkflow accepts current_user parameter
- _strategy_node injects infer_intent + interrupt_risk into prompt
- _execution_node enforces max_frequency_minutes throttle
- processQuery resolver passes current_user to workflow"
```

---

### 任务 9：文档更新

**覆盖规格：** §2.3（突发事件说明）+ §3.2（隐私声明）

**文件：**
- 修改：`AGENTS.md`
- 修改：`README.md`

- [ ] **步骤 1：更新 AGENTS.md 未解决问题列表**

删"反馈学习 no-op"、"多用户隔离未实现"、"规则引擎仅 4 场景"、"概率推断被移除"、"隐私保护未实现"条目，补：
```
1. 反馈学习：已实现——权重更新在 submit_feedback resolver 中
2. 规则引擎：已补全至 7 条（含 city_driving/traffic_jam/乘客在场），数据驱动加载
3. 概率推断：已实现——嵌入向量相似度 + 打断风险公式
4. 隐私保护：已实现——位置脱敏 + 数据导出/删除 mutation
5. 多用户隔离：已实现——全栈 per-user 目录（data/users/{user_id}/）
6. 突发事件处理：由 Strategy Agent + 规则引擎联合覆盖（无独立模块），论文中说明
```

- [ ] **步骤 2：更新 README.md 隐私声明**

```markdown
## 隐私保护

- 所有数据存储在本地 `data/users/` 目录下
- 无云端同步、无遥测、无第三方数据共享
- LLM 调用不发送原始记忆数据至外部——仅发送当前查询文本、规则约束及上下文摘要
- 用户可关闭记忆功能减少数据暴露
- 支持通过 GraphQL `exportData` / `deleteAllData` 导出或删除个人数据
```

- [ ] **步骤 3：Commit**

```bash
git add AGENTS.md README.md
git commit -m "docs: update for enhancement completion — gaps closed, privacy declaration

- remove resolved gap entries from AGENTS.md
- add privacy protection statement to README"
```

---

### 运行完整测试套件

所有任务完成后：

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
uv run pytest tests/ -v
```

---

**统计**：9 任务，9 次 commit。新增 9 文件（含 `test_mutation_feedback.py`），修改 17 文件。
