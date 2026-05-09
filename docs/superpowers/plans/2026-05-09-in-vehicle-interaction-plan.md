# 车载交互优化 实现计划

> **面向 AI 代理的工作者：** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 在现有四 Agent 流水线上补齐六项车载交互缺失——多格式输出、主动触发、流式响应、多轮对话、快捷指令、通道/打断统一。

**架构：** 在现有 `app/agents/`、`app/api/` 上加新模块，不改动核心流水线架构。各模块通过 workflow.py 注入点串联。模块 1→2→(3,4,5 顺序) 执行——3/4/5 均改 workflow.py，顺序避免合并冲突。

**技术栈：** Python 3.14, Pydantic, FastAPI SSE, TOMLStore (现有), pytest, Strawberry GraphQL (部分替代)

---

### 任务 1.0：创建 ProcessQueryInput/Result Pydantic schema

**文件：**
- 创建：`app/schemas/query.py`

- [ ] **步骤 1：创建 query.py**

```python
"""SSE 查询端点输入/输出 schema."""
from __future__ import annotations
from pydantic import BaseModel


class ProcessQueryRequest(BaseModel):
    """POST /query/stream 请求体."""
    query: str
    memory_mode: str = "memory_bank"
    context: dict | None = None
    current_user: str = "default"
    session_id: str | None = None


class ProcessQueryResult(BaseModel):
    """SSE 'done' 事件 data schema."""
    status: str = "delivered"  # "delivered" | "pending" | "suppressed"
    event_id: str | None = None
    session_id: str | None = None
    result: dict | None = None  # ReminderContent.model_dump()
    pending_reminder_id: str | None = None
    trigger_text: str | None = None
    reason: str | None = None
```

- [ ] **步骤 2：Commit**

```bash
git add app/schemas/query.py
git commit -m "feat: add ProcessQueryRequest/Result Pydantic schemas for SSE endpoint"
```

---

**文件：**
- 创建：`app/agents/outputs.py`
- 测试：`tests/test_outputs.py`

- [ ] **步骤 1：编写失败的测试**

```python
"""测试 OutputRouter 多格式输出与通道路由."""
import pytest
from app.agents.outputs import (
    InterruptLevel,
    MultiFormatContent,
    OutputChannel,
    OutputRouter,
)


class TestReminderContent:
    def test_reminder_content_all_fields_populated(self):
        """Given 完整字段, When 构造 MultiFormatContent, Then 所有字段正确."""
        rc = MultiFormatContent(
            speakable_text="3点开会",
            display_text="会议 · 15:00",
            detailed="会议提醒：下午3点",
            channel=OutputChannel.AUDIO,
            interrupt_level=InterruptLevel.NORMAL,
        )
        assert rc.speakable_text == "3点开会"
        assert rc.display_text == "会议 · 15:00"
        assert rc.channel == OutputChannel.AUDIO
        assert rc.interrupt_level == InterruptLevel.NORMAL  # Enum 比较用身份，非数值

    def test_reminder_content_is_json_serializable(self):
        """Given MultiFormatContent, When model_dump(), Then 枚举序列化为字符串."""
        rc = MultiFormatContent(
            speakable_text="3点开会",
            display_text="会议",
            detailed="会议提醒",
            channel=OutputChannel.AUDIO,
            interrupt_level=InterruptLevel.NORMAL,
        )
        d = rc.model_dump()
        assert d["channel"] == "audio"
        assert d["interrupt_level"] == 0


class TestOutputRouterSpeakableFallback:
    """speakable_text fallback 路径测试."""

    def test_llm_provided_speakable_used_directly(self):
        """Given LLM 已生成 speakable_text, When OutputRouter, Then 直接使用."""
        decision = {
            "should_remind": True,
            "reminder_content": {
                "speakable_text": "3点开会",
                "display_text": "会议15点",
                "detailed": "完整文本很长很长超过15字限制",
            },
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.speakable_text == "3点开会"

    def test_fallback_truncation(self):
        """Given LLM 未生成 speakable_text, When OutputRouter, Then 从 detailed 截断."""
        decision = {
            "should_remind": True,
            "reminder_content": {
                "detailed": "会议提醒下午3点公司3楼会议室确认参加",
            },
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert len(result.speakable_text) <= 15
        assert not result.speakable_text.endswith("。")

    def test_fallback_empty_detailed_default_text(self):
        """Given 所有内容为空, When OutputRouter, Then 兜底文本."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": ""},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.speakable_text == "提醒"


class TestOutputRouterInterruptLevel:
    """打断级别测试."""

    def test_emergency_is_immediate(self):
        """Given LLM 标记 is_emergency=true, When OutputRouter, Then interrupt_level=2."""
        decision = {
            "should_remind": True,
            "is_emergency": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.interrupt_level == InterruptLevel.URGENT_IMMEDIATE

    def test_only_urgent_is_urgent_normal(self):
        """Given rules_result.only_urgent=true, When OutputRouter, Then interrupt_level=1."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="city_driving",
            rules_result={"only_urgent": True},
        )
        assert result.interrupt_level == InterruptLevel.URGENT_NORMAL

    def test_normal_is_zero(self):
        """Given 普通事件, When OutputRouter, Then interrupt_level=0."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.interrupt_level == InterruptLevel.NORMAL


class TestOutputRouterChannel:
    """通道路由测试."""

    def test_rules_allowed_channels_takes_precedence(self):
        """Given rules_result 有 allowed_channels, When OutputRouter, Then 取第一优先."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="highway",
            rules_result={"allowed_channels": [OutputChannel.AUDIO, OutputChannel.VISUAL]},
        )
        assert result.channel == OutputChannel.AUDIO

    def test_empty_allowed_channels_defaults_visual(self):
        """Given 空 allowed_channels, When OutputRouter, Then 默认 VISUAL."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="city_driving",
            rules_result={"allowed_channels": []},
        )
        assert result.channel == OutputChannel.VISUAL
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_outputs.py -v
# 预期：全部 FAIL（模块不存在）
```

- [ ] **步骤 3：实现 outputs.py**

```python
"""多格式输出路由 + 通道 + 打断级别."""
from dataclasses import dataclass
from enum import Enum


class OutputChannel(Enum):
    AUDIO = "audio"
    VISUAL = "visual"
    DETAILED = "detailed"


class InterruptLevel(Enum):
    NORMAL = 0
    URGENT_NORMAL = 1
    URGENT_IMMEDIATE = 2


@dataclass
class MultiFormatContent:  # 注意：与 workflow.py 中的 ReminderContent 区分命名
    """多格式提醒内容。workflow.py 中已有 ReminderContent(Pydantic) 用于提取，
    此处为独立的输出路由结果类型。"""
    speakable_text: str
    display_text: str
    detailed: str
    channel: OutputChannel
    interrupt_level: InterruptLevel

    def model_dump(self) -> dict:
        return {
            "speakable_text": self.speakable_text,
            "display_text": self.display_text,
            "detailed": self.detailed,
            "channel": self.channel.value,
            "interrupt_level": self.interrupt_level.value,
        }


class OutputRouter:
    """决策 → ReminderContent 路由。处理 speakable_text/display_text fallback 和通道/打断级别。"""

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        t = str(text).strip("。！？,.!? \t\n")
        return t[:max_len] if t else "提醒"

    @staticmethod
    def _compute_channel(rules_result: dict) -> OutputChannel:
        allowed = rules_result.get("allowed_channels", [])
        if allowed:
            first = allowed[0]
            if isinstance(first, OutputChannel):
                return first
            try:
                return OutputChannel(first)
            except ValueError:
                pass
        return OutputChannel.VISUAL

    @staticmethod
    def _compute_interrupt_level(decision: dict, rules_result: dict) -> InterruptLevel:
        if decision.get("is_emergency"):
            return InterruptLevel.URGENT_IMMEDIATE
        if rules_result.get("only_urgent"):
            return InterruptLevel.URGENT_NORMAL
        return InterruptLevel.NORMAL

    def route(
        self, decision: dict, scenario: str, rules_result: dict
    ) -> MultiFormatContent:
        rc = decision.get("reminder_content", {})
        if isinstance(rc, str):
            rc = {"detailed": rc}
        detailed = rc.get("detailed", "") or ""

        speakable = rc.get("speakable_text", "")
        if not speakable:
            speakable = self._truncate(str(detailed), 15)

        display = rc.get("display_text", "")
        if not display:
            display = self._truncate(str(detailed), 20)

        return MultiFormatContent(
            speakable_text=str(speakable),
            display_text=str(display),
            detailed=str(detailed),
            channel=self._compute_channel(rules_result),
            interrupt_level=self._compute_interrupt_level(decision, rules_result),
        )
```

> ⚠ 注意：`OutputChannel` 和 `InterruptLevel` 为 `Enum`，`json.dumps` 直接序列化会抛 `TypeError`。一律通过 `model_dump()` → `json.dumps(result, ensure_ascii=False)` 路径，不可直接 dump 枚举对象。

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_outputs.py -v
# 预期：全部 PASS
```

- [ ] **步骤 5：Commit**

```bash
git add app/agents/outputs.py tests/test_outputs.py
git commit -m "feat: add OutputRouter with multi-channel output and interrupt levels"
```

---

### 任务 1.2：更新 Strategy Agent 提示词（多格式输出）

**文件：**
- 修改：`app/agents/prompts.py:25-34`

- [ ] **步骤 1：修改 STRATEGY_SYSTEM_PROMPT**

```python
STRATEGY_SYSTEM_PROMPT = """你是策略决策Agent，负责决定是否提醒及提醒方式。

基于上下文和任务信息，决定：
- 是否提醒（should_remind）
- 提醒时机（now/delay/skip/location）
- 是否为紧急事件（is_emergency）——如急救、事故预警、儿童遗留检测
- reminder_content 对象，包含三种格式：
  * speakable_text：可播报文本，≤15字，无标点符号。如"3点公司3楼会议"
  * display_text：车机显示文本，≤20字。如"会议 · 15:00 · 公司3F"
  * detailed：完整文本（停车时可查看详情）
- 决策理由

输出JSON格式。示例：
{
  "should_remind": true,
  "timing": "now",
  "is_emergency": false,
  "reminder_content": {
    "speakable_text": "3点公司3楼会议",
    "display_text": "会议 · 15:00 · 公司3F",
    "detailed": "会议提醒：下午3点在公司3楼会议室"
  },
  "reason": "用户请求会议提醒"
}

考虑个性化策略和安全边界。"""
```

- [ ] **步骤 2：Commit**

```bash
git add app/agents/prompts.py
git commit -m "feat: update Strategy prompt for multi-format reminder_content"
```

---

### 任务 1.3：修改 rules.py 通道类型转换

**文件：**
- 修改：`app/agents/rules.py:197-198`

- [ ] **步骤 1：format_constraints 中将通道字符串转 OutputChannel**

在 `format_constraints()` 中，`allowed_channels` 已是字符串列表（来自 TOML），无需改动。但需在 `apply_rules()` 返回前确保类型一致——当前已返回字符串列表，OutputRouter 的 `_compute_channel` 已处理字符串转枚举。**无需改 rules.py**。

但需要验证：`rules.py` 中 `_CONSTRAINT_FIELDS` 未包含 `extra_channels`——检查后发现已在 L115-123 中：

```python
_CONSTRAINT_FIELDS = frozenset(
    {
        "allowed_channels",
        "max_frequency_minutes",
        "only_urgent",
        "postpone",
        "extra_channels",
    }
)
```

结论：rules.py 无需改动。OutputRouter 的 `_compute_channel` 接受 `OutputChannel` 枚举或字符串，已处理兼容。

- [ ] **步骤 1：验证无改动需求**

```bash
uv run pytest tests/test_rules.py -v
# 预期：全部 PASS（现有测试不变）
```

- [ ] **步骤 2：Commit（空——跳过此任务）**

---

### 任务 1.4：修改 workflow.py Execution Agent 接入 OutputRouter

**文件：**
- 修改：`app/agents/workflow.py:307-383`（_execution_node）
- 修改：`app/agents/workflow.py:409`（run_with_stages 返回类型）
- 修改：`app/agents/state.py:14-17`（AgentState 增加新字段）
- 修改：`app/agents/state.py:27`（WorkflowStages.execution 类型适配）

- [ ] **步骤 1：更新 AgentState 和 WorkflowStages**

```python
# app/agents/state.py
from typing import NotRequired

class AgentState(TypedDict):
    original_query: str
    context: dict
    task: dict | None
    decision: dict | None
    result: str | None
    event_id: str | None
    driving_context: dict | None
    stages: WorkflowStages | None
    output_content: NotRequired[dict | None]   # ReminderContent.model_dump()
    session_id: NotRequired[str | None]
    pending_reminder_id: NotRequired[str | None]
    action_result: NotRequired[dict | None]


@dataclass
class WorkflowStages:
    context: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)  # 保持 dict，容纳更多字段
```

- [ ] **步骤 2：修改 _execution_node**

在 `_execution_node` 末尾，`result = f"提醒已发送: {content}"` 之后，调用 OutputRouter：

```python
# 在 workflow.py 顶部新增 import
from app.agents.outputs import OutputRouter

# 在 _execution_node 内，result = f"提醒已发送: {content}" 之前插入：
        # --- 多格式输出路由 ---
        output_router = OutputRouter()
        scenario = driving_ctx.get("scenario", "") if driving_ctx else ""
        rules_result = apply_rules(driving_ctx) if driving_ctx else {}
        output_content = output_router.route(decision, scenario, rules_result)

        # result 字段保留为兼容文本（当前行为），同时返回 output_content
        result = f"提醒已发送: {content}"
        if stages is not None:
            stages.execution = {
                "content": content,
                "event_id": event_id,
                "result": result,
                "output": output_content.model_dump(),
            }
        return {
            "result": result,
            "event_id": event_id,
            "output_content": output_content.model_dump(),
        }
```

注意：当前 `_execution_node` 在 should_remind=False / postpone / freq_guard 三个早退分支中返回 `{"result": ..., "event_id": None}`，这些分支不经过 OutputRouter（无提醒内容），无需改动。

- [ ] **步骤 3：运行现有测试验证无回归**

```bash
uv run pytest tests/test_graphql.py -v
# 预期：全部 PASS（现有 processQuery 行为不变）
```

- [ ] **步骤 4：Commit**

```bash
git add app/agents/state.py app/agents/workflow.py
git commit -m "feat: integrate OutputRouter into Execution Agent for multi-format output"
```

---

## 模块 2：主动触发框架

### 任务 2.1：创建 PendingReminderManager

**文件：**
- 创建：`app/agents/pending.py`
- 测试：`tests/test_pending.py`

- [ ] **步骤 1：编写失败的测试**

```python
"""测试 PendingReminderManager."""
import pytest
from pathlib import Path
from datetime import UTC, datetime, timedelta
from app.agents.pending import PendingReminderManager
from app.agents.outputs import MultiFormatContent, OutputChannel, InterruptLevel


@pytest.fixture
def tmp_user_dir(tmp_path):
    return tmp_path / "default"


@pytest.fixture
def sample_content():
    return MultiFormatContent(
        speakable_text="到家提醒",
        display_text="到家",
        detailed="到家提醒",
        channel=OutputChannel.AUDIO,
        interrupt_level=InterruptLevel.NORMAL,
    )


class TestPendingReminderCRUD:
    async def test_add_and_list(self, tmp_user_dir, sample_content):
        """Given 空 PendingReminderManager, When add 一条提醒, Then list 返回1条."""
        pm = PendingReminderManager(tmp_user_dir)
        pr = await pm.add(
            content=sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            ttl_seconds=3600,
        )
        assert pr.id.startswith("pr_")
        assert pr.status == "pending"

        all_reminders = await pm.list_pending()
        assert len(all_reminders) == 1

    async def test_cancel(self, tmp_user_dir, sample_content):
        """Given 一条 pending reminder, When cancel, Then status 变为 cancelled."""
        pm = PendingReminderManager(tmp_user_dir)
        pr = await pm.add(sample_content, "location", {}, "evt_001")
        await pm.cancel(pr.id)
        assert len(await pm.list_pending()) == 0


class TestPollingTrigger:
    async def test_location_trigger_within_500m(self, tmp_user_dir, sample_content):
        """Given location trigger, When GPS 在 500m 内, Then 触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            ttl_seconds=3600,
        )
        # 当前位置距目标约 0m → 应触发
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 31.23, "longitude": 121.47}}}
        )
        assert len(triggered) == 1

    async def test_location_too_far_not_triggered(self, tmp_user_dir, sample_content):
        """Given location trigger, When GPS 距离 > 500m, Then 不触发."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            ttl_seconds=3600,
        )
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 30.00, "longitude": 120.00}}}
        )
        assert len(triggered) == 0

    async def test_parked_triggers_immediately(self, tmp_user_dir, sample_content):
        """Given location trigger, When scenario=parked, Then 立即触发（不等距离）."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            ttl_seconds=3600,
        )
        triggered = await pm.poll(
            {
                "scenario": "parked",
                "spatial": {"current_location": {"latitude": 30.00, "longitude": 120.00}},
            }
        )
        assert len(triggered) == 1

    async def test_ttl_expiry(self, tmp_user_dir, sample_content):
        """Given TTL=1s, When 等待 2s 后 poll, Then 自动 cancel."""
        pm = PendingReminderManager(tmp_user_dir)
        await pm.add(
            sample_content,
            trigger_type="location",
            trigger_target={"latitude": 31.23, "longitude": 121.47},
            event_id="evt_001",
            ttl_seconds=1,
        )
        import asyncio
        await asyncio.sleep(1.5)
        triggered = await pm.poll(
            {"spatial": {"current_location": {"latitude": 31.23, "longitude": 121.47}}}
        )
        assert len(triggered) == 0  # 已 TTL 过期
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_pending.py -v
# 预期：全部 FAIL
```

- [ ] **步骤 3：实现 pending.py**

接口与关键思路：

```python
"""主动触发框架——PendingReminder 管理和轮询触发."""
import hashlib
import math
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from dataclasses import dataclass, field
from app.agents.outputs import MultiFormatContent
from app.storage.toml_store import TOMLStore


@dataclass
class PendingReminder:
    id: str
    event_id: str
    content: dict  # ReminderContent.model_dump()
    trigger_type: str  # "location" | "time"
    trigger_target: dict
    trigger_text: str  # 人类可读触发条件，如"到达公司附近时"
    status: str  # "pending" | "triggered" | "cancelled"
    created_at: str
    ttl_seconds: int

    @classmethod
    def new(
        cls,
        content: MultiFormatContent,
        trigger_type: str,
        trigger_target: dict,
        event_id: str,
        trigger_text: str = "",
        ttl_seconds: int = 3600,
    ) -> "PendingReminder":
        return cls(
            id=f"pr_{uuid.uuid4().hex[:12]}",
            event_id=event_id,
            content=content.model_dump(),
            trigger_type=trigger_type,
            trigger_target=trigger_target,
            trigger_text=trigger_text,
            status="pending",
            created_at=datetime.now(UTC).isoformat(),
            ttl_seconds=ttl_seconds,
        )


class PendingReminderManager:
    def __init__(self, user_dir: Path):
        self._store = TOMLStore(
            user_dir=user_dir,
            filename="pending_reminders.toml",
            default_factory=list,
        )

    async def _read_all(self) -> list[dict]:
        return await self._store.read()

    async def _write_all(self, reminders: list[dict]):
        await self._store.write(reminders)

    async def add(self, content, trigger_type, trigger_target, event_id, ttl_seconds=None, trigger_text=""):
        if ttl_seconds is None:
            if trigger_type == "time":
                # time 类型 TTL = (目标时间 - 当前时间) + 1800s
                target_str = trigger_target.get("time", "")
                try:
                    target_dt = datetime.fromisoformat(target_str)
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=UTC)
                    delta = (target_dt - datetime.now(UTC)).total_seconds()
                    ttl_seconds = int(max(delta, 0)) + 1800
                except (ValueError, TypeError):
                    ttl_seconds = 3600
            else:
                ttl_seconds = 3600
        pr = PendingReminder.new(content, trigger_type, trigger_target, event_id, trigger_text, ttl_seconds)
        all_rem = await self._read_all()
        all_rem.append(pr.__dict__)
        await self._write_all(all_rem)
        return pr

    async def list_pending(self) -> list[dict]:
        all_rem = await self._read_all()
        return [r for r in all_rem if r.get("status") == "pending"]

    async def cancel(self, reminder_id: str):
        all_rem = await self._read_all()
        for r in all_rem:
            if r.get("id") == reminder_id:
                r["status"] = "cancelled"
        await self._write_all(all_rem)

    async def cancel_last(self) -> bool:
        """取消最近一条 pending reminder。返回是否成功取消。"""
        all_rem = await self._read_all()
        pending = [r for r in all_rem if r.get("status") == "pending"]
        if not pending:
            return False
        pending[-1]["status"] = "cancelled"
        await self._write_all(all_rem)
        return True

    async def poll(self, driving_context: dict) -> list[dict]:
        """返回满足触发条件的提醒列表，并将其标记为 triggered。"""
        all_rem = await self._read_all()
        triggered = []
        now = datetime.now(UTC)
        for r in all_rem:
            if r.get("status") != "pending":
                continue
            # TTL 超时
            created = datetime.fromisoformat(r["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if (now - created).total_seconds() > r.get("ttl_seconds", 3600):
                r["status"] = "cancelled"
                continue
            # 触发评估
            trigger_type = r.get("trigger_type", "")
            if trigger_type == "location":
                if self._check_location(r, ctx):
                    r["status"] = "triggered"
                    triggered.append(r)
            elif trigger_type == "time":
                if self._check_time(r):
                    r["status"] = "triggered"
                    triggered.append(r)
            elif trigger_type == "context":
                if self._check_context(r, ctx):
                    r["status"] = "triggered"
                    triggered.append(r)
        if triggered:
            await self._write_all(all_rem)
        return triggered

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        """返回两点间距离（米）。"""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    @staticmethod
    def _check_location(reminder: dict, ctx: dict) -> bool:
        target = reminder.get("trigger_target", {})
        spatial = ctx.get("spatial", {}) or {}
        cur_loc = spatial.get("current_location", {}) or {}
        if not cur_loc:
            return False
        # 停车 → 立即触发
        if ctx.get("scenario") == "parked":
            return True
        target_lat = target.get("latitude")
        target_lon = target.get("longitude")
        if target_lat is None or target_lon is None:
            return False
        dist = PendingReminderManager._haversine(
            cur_loc.get("latitude", 0), cur_loc.get("longitude", 0),
            target_lat, target_lon,
        )
        return dist < 500

    @staticmethod
    def _check_time(reminder: dict) -> bool:
        target = reminder.get("trigger_target", {})
        target_time_str = target.get("time", "")
        if not target_time_str:
            return False
        try:
            target_time = datetime.fromisoformat(target_time_str)
        except (ValueError, TypeError):
            return False
        return datetime.now(UTC) >= target_time.replace(tzinfo=UTC)

    @staticmethod
    def _check_context(reminder: dict, ctx: dict) -> bool:
        """context 触发：当前 scenario != 入队时的 scenario（场景切换）。"""
        target = reminder.get("trigger_target", {})
        prev = target.get("previous_scenario", "")
        current = ctx.get("scenario", "")
        return bool(prev) and bool(current) and prev != current
```

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_pending.py -v
# 预期：全部 PASS
```

- [ ] **步骤 5：Commit**

```bash
git add app/agents/pending.py tests/test_pending.py
git commit -m "feat: add PendingReminderManager with polling trigger evaluation"
```

---

### 任务 2.2：集成 PendingReminderManager 到 Execution Agent

**文件：**
- 修改：`app/agents/workflow.py:310-383`

- [ ] **步骤 1：在 _execution_node 中增加 PendingReminder 创建 + cancel_last 处理**

在 `_execution_node` 开头（decision 提取后、规则硬约束之前）增加 cancel_last action 处理：

```python
    # 在 _execution_node 内，decision = state.get("decision") or {} 之后插入：
    action = decision.get("action", "")
    if action == "cancel_last":
        from app.agents.pending import PendingReminderManager
        pm = PendingReminderManager(user_data_dir(self.current_user))
        cancelled = await pm.cancel_last()
        result = "提醒已取消" if cancelled else "暂无待取消的提醒"
        if stages is not None:
            stages.execution = {"content": None, "event_id": None, "result": result, "cancelled": cancelled}
        return {"result": result, "event_id": None, "action_result": {"cancelled": cancelled}}
```

然后在 postpone + timing 检查处增加 PendingReminder 创建：

```python
# 在 workflow.py 顶部新增 import
from app.agents.pending import PendingReminderManager
from app.config import user_data_dir

# 在 _execution_node 内，postpone 分支替换：
        postpone = decision.get("postpone", False)
        timing = decision.get("timing", "")
        if postpone or timing in ("delay", "location", "location_time"):
            # --- 创建 PendingReminder ---
            pm = PendingReminderManager(user_data_dir(self.current_user))
            
            # 构造 content（需先过 OutputRouter）
            output_router = OutputRouter()
            scenario = driving_ctx.get("scenario", "") if driving_ctx else ""
            rules_result = apply_rules(driving_ctx) if driving_ctx else {}
            output_content = output_router.route(decision, scenario, rules_result)
            
            # 确定 trigger_type 和 trigger_target
            trigger_type, trigger_target = _map_pending_trigger(decision, driving_ctx)
            
            pr = await pm.add(
                content=output_content,
                trigger_type=trigger_type,
                trigger_target=trigger_target,
                event_id="",  # 尚未写入记忆
                ttl_seconds=3600,
            )
            result = f"提醒已延后：{decision.get('reason', '')}。将在{pr.trigger_type}条件满足时提醒"
            if stages is not None:
                stages.execution = {
                    "content": None,
                    "event_id": None,
                    "result": result,
                    "pending_reminder_id": pr.id,
                }
            return {
                "result": result,
                "event_id": None,
                "output_content": output_content.model_dump(),
                "pending_reminder_id": pr.id,
                "status": "pending",
            }
```

`_map_pending_trigger()` 为模块级辅助函数（`_execution_node` 上方定义）：

```python
def _extract_location_target(decision: dict, driving_ctx: dict | None) -> dict:
    """从 driving_context 中提取目标位置经纬度."""
    if driving_ctx:
        spatial = driving_ctx.get("spatial", {}) or {}
        dest = spatial.get("destination", {}) or {}
        if dest.get("latitude") is not None:
            return {"latitude": dest["latitude"], "longitude": dest["longitude"]}
    return {}

def _map_pending_trigger(decision: dict, driving_ctx: dict | None):
    """从 decision 映射 trigger_type 和 trigger_target。返回 (type, target, text) 三元组。"""
    timing = decision.get("timing", "")
    if timing == "location":
        return "location", _extract_location_target(decision, driving_ctx), "到达目的地时"
    if timing == "location_time":
        # 创建两个 PendingReminder：一个 location + 一个 time
        return "location_time", {
            "location": _extract_location_target(decision, driving_ctx),
            "time": decision.get("target_time", ""),
        }, "到达目的地或到时间时"
    target_time = decision.get("target_time", "")
    if target_time:
        return "time", {"time": target_time}, f"{target_time} 时"
    if driving_ctx:
        return "context", {"previous_scenario": driving_ctx.get("scenario", "")}, "驾驶状态恢复时"
    return "time", {"time": ""}, ""
```

在 `_execution_node` 中创建 PendingReminder 时处理 `location_time` 复合：

```python
        if postpone or timing in ("delay", "location", "location_time"):
            pm = PendingReminderManager(user_data_dir(self.current_user))
            # ... (OutputRouter 逻辑同上) ...
            
            trigger_type, trigger_target, trigger_text = _map_pending_trigger(decision, driving_ctx)
            
            if trigger_type == "location_time":
                # 拆为两个独立 PendingReminder
                loc_target = trigger_target.get("location", {})
                time_target = trigger_target.get("time", "")
                pr1 = await pm.add(content=output_content, trigger_type="location",
                                    trigger_target=loc_target, event_id="",
                                    trigger_text=f"到达目的地时")
                pr2 = await pm.add(content=output_content, trigger_type="time",
                                    trigger_target={"time": time_target}, event_id="",
                                    trigger_text=f"到达 {time_target} 时")
                pending_ids = [pr1.id, pr2.id]
            else:
                pr = await pm.add(
                    content=output_content,
                    trigger_type=trigger_type,
                    trigger_target=trigger_target,
                    event_id="",
                    trigger_text=trigger_text,
                )
                pending_ids = [pr.id]
```

- [ ] **步骤 2：运行现有测试验证无回归**

```bash
uv run pytest tests/ -v --ignore=tests/test_pending.py --ignore=tests/test_outputs.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: integrate PendingReminderManager into Execution Agent for delayed triggers"
```

---

### 任务 2.3：新增 GraphQL mutations（pollPendingReminders 等）

**文件：**
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/mutation.py`

- [ ] **步骤 1：在 graphql_schema.py 增加新类型**

```python
# 新增 Strawberry 类型
@strawberry.type
class PendingReminderGQL:
    id: str
    event_id: str
    trigger_type: str
    trigger_text: str
    status: str
    created_at: str

@strawberry.type
class TriggeredReminderGQL:
    id: str
    event_id: str
    content: JSON
    triggered_at: str

@strawberry.type
class PollResult:
    triggered: list[TriggeredReminderGQL]
```

- [ ] **步骤 2：在 mutation.py 增加 3 个 resolver**

```python
# 新增 import
from app.agents.pending import PendingReminderManager
from app.api.graphql_schema import PendingReminderGQL, TriggeredReminderGQL, PollResult

# 在 Mutation 类中新增：

    @strawberry.mutation
    async def poll_pending_reminders(
        self,
        current_user: str = "default",
        context_input: DrivingContextInput | None = None,
    ) -> PollResult:
        """车机端轮询待触发提醒."""
        pm = PendingReminderManager(user_data_dir(current_user))
        ctx = {}
        if context_input:
            ctx = input_to_context(context_input).model_dump()
        triggered = await pm.poll(ctx)
        return PollResult(
            triggered=[
                TriggeredReminderGQL(
                    id=r["id"],
                    event_id=r.get("event_id", ""),
                    content=cast("JSON", r.get("content", {})),
                    triggered_at=datetime.now(UTC).isoformat(),
                )
                for r in triggered
            ]
        )

    @strawberry.mutation
    async def cancel_pending_reminder(
        self,
        reminder_id: str,
        current_user: str = "default",
    ) -> bool:
        pm = PendingReminderManager(user_data_dir(current_user))
        await pm.cancel(reminder_id)
        return True

    @strawberry.mutation
    async def get_pending_reminders(
        self,
        current_user: str = "default",
    ) -> list[PendingReminderGQL]:
        pm = PendingReminderManager(user_data_dir(current_user))
        pending = await pm.list_pending()
        return [
            PendingReminderGQL(
                id=r["id"],
                event_id=r.get("event_id", ""),
                trigger_type=r.get("trigger_type", ""),
                trigger_text=r.get("trigger_text", ""),
                status=r.get("status", ""),
                created_at=r.get("created_at", ""),
            )
            for r in pending
        ]
```

- [ ] **步骤 3：运行 GraphQL 测试**

```bash
uv run pytest tests/test_graphql.py -v
```

- [ ] **步骤 4：Commit**

```bash
git add app/api/graphql_schema.py app/api/resolvers/mutation.py
git commit -m "feat: add pollPendingReminders/cancelPendingReminder/getPendingReminders mutations"
```

---

## 模块 3：流式响应

### 任务 3.1：新增 run_stream() 生成器

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：在 AgentWorkflow 类中增加 run_stream()**

```python
# 设计说明：run_stream() 返回 list[dict]（非 async generator）。
# 阶段间推送（context_done → task_done → decision → done）提供进度可见性，
# 用户在 1~3s 后就能看到部分结果，无需等全部完。这是阶段级流式，非 token 级。
    async def run_stream(
        self, user_input: str,
        driving_context: dict | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        events: list[dict] = []
        stages = WorkflowStages()
        state: AgentState = { ... }  # 同 run_with_stages
        
        # Stage 1: Context
        events.append({"event": "stage_start", "data": {"stage": "context"}})
        updates = await self._context_node(state)
        state.update(updates)
        events.append({"event": "context_done", "data": {"context": state["context"]}})
        
        # Stage 2: Task
        events.append({"event": "stage_start", "data": {"stage": "task"}})
        updates = await self._task_node(state)
        state.update(updates)
        events.append({"event": "task_done", "data": {"tasks": state.get("task") or {}}})
        
        # Stage 3: Strategy
        events.append({"event": "stage_start", "data": {"stage": "strategy"}})
        updates = await self._strategy_node(state)
        state.update(updates)
        events.append({"event": "decision", "data": {"should_remind": (state.get("decision") or {}).get("should_remind")}})
        
        # Stage 4: Execution
        events.append({"event": "stage_start", "data": {"stage": "execution"}})
        updates = await self._execution_node(state)
        state.update(updates)
        
        # done 事件
        done_data = {"event_id": state.get("event_id"), "session_id": session_id}
        pending_id = state.get("pending_reminder_id")
        if pending_id:
            done_data["status"] = "pending"
            done_data["pending_reminder_id"] = pending_id
        elif state.get("result") and "取消" in str(state.get("result")):
            done_data["status"] = "suppressed"
            done_data["reason"] = state.get("result")
        else:
            done_data["status"] = "delivered"
            done_data["result"] = state.get("output_content") or state.get("result")
        events.append({"event": "done", "data": done_data})
        return events
```

- [ ] **步骤 2：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: add run_stream() generator for SSE streaming pipeline"
```

---

### 任务 3.2：新增 SSE 端点

**文件：**
- 创建：`app/api/stream.py`
- 修改：`app/api/main.py`
- 测试：`tests/test_stream.py`
- 参考：`app/schemas/query.py`（任务 1.0 创建）

- [ ] **步骤 1：创建 stream.py**

```python
"""SSE 流式查询端点."""
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.workflow import AgentWorkflow
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.query import ProcessQueryRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query/stream")
async def query_stream(req: ProcessQueryRequest):
    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_mode=MemoryMode(req.memory_mode),
        memory_module=mm,
        current_user=req.current_user,
    )

    driving_context = req.context  # already dict from JSON body

    async def event_generator():
        try:
            events = await workflow.run_stream(
                req.query, driving_context, session_id=req.session_id,
            )
            for event in events:
                data_str = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['event']}\ndata: {data_str}\n\n"
        except Exception as e:
            logger.exception("Stream error")
            err = json.dumps({"code": "INTERNAL", "message": str(e)})
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **步骤 2：在 main.py 注册路由**

```python
# 在 main.py 中新增 import
from app.api.stream import router as stream_router

# 在 _mount_graphql() 之后新增
app.include_router(stream_router)
```

注意：`run_stream()` 方法中使用 `async for` 需将其改为异步生成器。实际上 `run_stream` 不是 async generator，它需要在每个 yield 处 `await` 后才能继续。设计为：

```python
# 简化：run_stream 返回普通 list，在 stream.py 中遍历
async def run_stream(self, ...):
    events = []
    ... (同前述逻辑)
    events.append({"event": "context_done", "data": ...})
    ...
    return events

# 或改为真正 async generator。此处选择简单路径——一次性收集所有事件返回 list，
# 然后 SSE 端逐个发送。LLM 调用是阻塞的，无法真正流式到 token 级别。
```

**实际设计选择：** `run_stream()` 返回 `list[dict]`，每个 dict 为 `{"event": ..., "data": ...}`。SSE 端遍历 list 逐个 yield。延迟改善来自阶段间推送（用户在第 1s 看到 context_done，不需等 6s 再看完整结果），非 token 级流式。

- [ ] **步骤 3：编写 SSE 集成测试并 Commit**

```python
# tests/test_stream.py
"""SSE 端点集成测试."""
import json
import pytest
from httpx import AsyncClient, ASGITransport
from app.api.main import app


@pytest.mark.integration
class TestStreamEndpoint:
    async def test_basic_stream(self):
        """POST /query/stream 返回 SSE 事件流."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST", "/query/stream",
                json={"query": "提醒我开会", "current_user": "test_user"},
                timeout=30,
            ) as response:
                assert response.status_code == 200
                events = []
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line)
                assert any("done" in e for e in events), f"No done event in {events}"

    async def test_stream_with_context(self):
        """带 driving_context 的流式请求."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST", "/query/stream",
                json={
                    "query": "提醒我",
                    "context": {"scenario": "parked"},
                    "current_user": "test_user",
                },
                timeout=30,
            ) as response:
                assert response.status_code == 200
                body = await response.aread()
                assert b"event: done" in body
```

```bash
git add app/api/stream.py app/api/main.py tests/test_stream.py
git commit -m "feat: add SSE /query/stream endpoint with stage-level progress events"
```

---

## 模块 4：多轮对话

### 任务 4.1：创建 ConversationManager

**文件：**
- 创建：`app/agents/conversation.py`
- 测试：`tests/test_conversation.py`

- [ ] **步骤 1：编写测试**

```python
"""测试 ConversationManager."""
import pytest
from datetime import UTC, datetime
from app.agents.conversation import ConversationManager, ConversationTurn


class TestConversationManager:
    async def test_create_and_add_turn(self):
        """Given 新会话, When 追加 turn, Then 轮次数正确."""
        cm = ConversationManager()
        sid = cm.create("user1")
        cm.add_turn(sid, "提醒我到公司", {"should_remind": True, "type": "travel"})
        history = cm.get_history(sid)
        assert len(history) == 1
        assert history[0].query == "提醒我到公司"

    async def test_history_limited_to_10(self):
        """Given 追加 12 轮, When get_history, Then 仅返回最近 10."""
        cm = ConversationManager()
        sid = cm.create("user1")
        for i in range(12):
            cm.add_turn(sid, f"query{i}", {"type": "test"}, f"response{i}")
        assert len(cm.get_history(sid)) == 10

    async def test_close_removes_session(self):
        """Given 活跃会话, When close, Then 会话不存在."""
        cm = ConversationManager()
        sid = cm.create("user1")
        cm.close(sid)
        assert cm.get_history(sid) == []

    async def test_cleanup_expired_sessions(self):
        """Given 超时会话, When cleanup, Then 移除."""
        cm = ConversationManager()
        sid = cm.create("user1")
        # 手动设置过去时间
        cm._sessions[sid]["last_activity"] = "2000-01-01T00:00:00"
        cm.cleanup_expired()
        assert cm.get_history(sid) == []
```

- [ ] **步骤 2：实现 conversation.py**

```python
"""会话管理——多轮对话支持."""
import uuid
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass


@dataclass
class ConversationTurn:
    turn_id: int
    query: str
    decision_snapshot: dict
    response_summary: str = ""
    timestamp: str = ""


class ConversationManager:
    def __init__(self, ttl_minutes: int = 30):
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl_minutes

    def create(self, user_id: str) -> str:
        sid = f"s_{uuid.uuid4().hex[:12]}"
        self._sessions[sid] = {
            "session_id": sid,
            "user_id": user_id,
            "created_at": datetime.now(UTC).isoformat(),
            "last_activity": datetime.now(UTC).isoformat(),
            "turns": [],
        }
        return sid

    def _exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def add_turn(
        self,
        session_id: str,
        query: str,
        decision_snapshot: dict,
        response_summary: str = "",
    ):
        if not self._exists(session_id):
            return
        session = self._sessions[session_id]
        turn = ConversationTurn(
            turn_id=len(session["turns"]) + 1,
            query=query,
            decision_snapshot=decision_snapshot,
            response_summary=response_summary,
            timestamp=datetime.now(UTC).isoformat(),
        )
        session["turns"].append(turn)
        if len(session["turns"]) > 10:
            session["turns"] = session["turns"][-10:]
        session["last_activity"] = datetime.now(UTC).isoformat()

    def get_history(self, session_id: str) -> list[ConversationTurn]:
        if not self._exists(session_id):
            return []
        session = self._sessions[session_id]
        # 惰性检查是否过期
        try:
            last = datetime.fromisoformat(session["last_activity"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if datetime.now(UTC) - last > timedelta(minutes=self._ttl):
                del self._sessions[session_id]
                return []
        except (ValueError, TypeError):
            pass
        return list(session["turns"])

    def close(self, session_id: str):
        self._sessions.pop(session_id, None)

    def cleanup_expired(self):
        now = datetime.now(UTC)
        expired = []
        for sid, session in list(self._sessions.items()):
            try:
                last = datetime.fromisoformat(session["last_activity"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if now - last > timedelta(minutes=self._ttl):
                    expired.append(sid)
            except (ValueError, TypeError):
                expired.append(sid)
        for sid in expired:
            del self._sessions[sid]


# 模块级单例（供 mutation 和 workflow 共享）
_conversation_manager = ConversationManager()
```

在 lifespan（`app/api/main.py`）中启动定期清理任务：

```python
# main.py _lifespan 内新增
import asyncio

async def _periodic_cleanup():
    while True:
        await asyncio.sleep(300)  # 每 5 分钟
        from app.agents.conversation import _conversation_manager
        _conversation_manager.cleanup_expired()

cleanup_task = asyncio.create_task(_periodic_cleanup())
yield
cleanup_task.cancel()
try:
    await cleanup_task
except asyncio.CancelledError:
    pass
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_conversation.py -v
```

- [ ] **步骤 4：Commit**

```bash
git add app/agents/conversation.py tests/test_conversation.py
git commit -m "feat: add ConversationManager for multi-turn dialog support"
```

---

### 任务 4.2：注入 conversation_history 到 Context Agent

**文件：**
- 修改：`app/agents/workflow.py:159-196`（_context_node）

- [ ] **步骤 1：在 _context_node 中增加 conversation_history**

```python
# 在 workflow.py 顶部新增 import
from app.agents.conversation import ConversationManager

# 在 AgentWorkflow.__init__ 中新增
self._conversations = ConversationManager()

# 修改 _context_node：
async def _context_node(self, state: AgentState) -> dict:
    user_input = state.get("original_query", "")
    stages = state.get("stages")
    session_id = state.get("session_id")

    relevant_memories = await self._search_memories(user_input)

    # --- 多轮对话：注入对话历史 ---
    conversation_history = []
    if session_id:
        turns = self._conversations.get_history(session_id)
        conversation_history = [
            {
                "turn": t.turn_id,
                "user": t.query,
                "assistant_summary": t.response_summary,
                "intent": t.decision_snapshot,
            }
            for t in turns
        ]

    current_datetime = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    driving_context = state.get("driving_context")

    if driving_context:
        context = dict(driving_context)
        context["current_datetime"] = current_datetime
        context["related_events"] = relevant_memories
        if conversation_history:
            context["conversation_history"] = conversation_history
    else:
        system_prompt = SYSTEM_PROMPTS["context"].format(
            current_datetime=current_datetime,
        )
        history_block = ""
        if conversation_history:
            history_block = (
                "\n对话历史: "
                + json.dumps(conversation_history, ensure_ascii=False)
                + "\n请结合对话历史理解指代（如"刚才那个"指上一轮的 entities）。"
            )

        prompt = f"""{system_prompt}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}{history_block}

请输出JSON格式的上下文对象. """

        parsed = await self._call_llm_json(prompt)
        context = {
            **parsed.model_dump(),
            "current_datetime": current_datetime,
            "related_events": relevant_memories,
        }

    if stages is not None:
        stages.context = context

    return {
        "context": context,
    }
```

- [ ] **步骤 2：在 run_with_stages() 和 run_stream() 中支持 session_id**

在 `run_with_stages` 签名增加 `session_id: str | None = None`，状态构造时传入 `"session_id": session_id`。执行完成后调用：

```python
# run_with_stages 末尾，return 之前：
if session_id:
    self._conversations.add_turn(
        session_id,
        user_input,
        state.get("decision") or {},
        state.get("result", ""),
    )
```

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: inject conversation history into Context Agent for multi-turn dialog"
```

---

### 任务 4.3：新增 closeSession mutation

**文件：**
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/mutation.py`

- [ ] **步骤 1：在 mutation.py 增加 closeSession**

```python
@strawberry.mutation
async def close_session(
    self,
    session_id: str,
    current_user: str = "default",
) -> bool:
    """关闭会话。需要在 AgentWorkflow 层级暴露 _conversations。"""
    # conversation 为 per-process 内存对象——通过 MemoryModule 或全局注册表访问
    # 简化方案：ConversationManager 作为模块级单例
    from app.agents.conversation import _conversation_manager
    _conversation_manager.close(session_id)
    return True
```

在 `conversation.py` 中：

```python
# 模块级单例（供 mutation 和 workflow 共享）
_conversation_manager = ConversationManager()
```

在 `workflow.py` 中替换 `self._conversations = ConversationManager()` 为 `self._conversations = _conversation_manager`。

- [ ] **步骤 2：Commit**

```bash
git add app/api/graphql_schema.py app/api/resolvers/mutation.py app/agents/conversation.py app/agents/workflow.py
git commit -m "feat: add closeSession mutation for conversation lifecycle"
```

---

## 模块 5：快捷指令

### 任务 5.1：创建快捷指令表与解析器

**文件：**
- 创建：`config/shortcuts.toml`
- 创建：`app/agents/shortcuts.py`
- 测试：`tests/test_shortcuts.py`

- [ ] **步骤 1：创建 shortcuts.toml**

```toml
[[shortcuts]]
patterns = ["提醒到家", "到家提醒", "到家叫我"]
type = "travel"
location = "home"
speakable_text = "到家提醒已设"
display_text = "到家提醒 · 已设"
priority = 10

[[shortcuts]]
patterns = ["提醒到公司", "到公司提醒", "公司提醒"]
type = "travel"
location = "office"
speakable_text = "公司提醒已设"
display_text = "公司提醒 · 已设"
priority = 9

[[shortcuts]]
patterns = ["取消提醒"]
type = "action"
action = "cancel_last"
speakable_text = "提醒已取消"
display_text = "已取消"
priority = 8

[[shortcuts]]
patterns = ["延迟"]
type = "action"
action = "snooze"
speakable_text = "已延迟"
display_text = "已延迟"
priority = 5
```

- [ ] **步骤 2：编写测试**

```python
"""测试 ShortcutResolver."""
import pytest
from app.agents.shortcuts import ShortcutResolver, parse_duration


class TestExactMatch:
    def test_remind_home(self):
        sr = ShortcutResolver()
        result = sr.resolve("提醒到家")
        assert result is not None
        assert result["type"] == "travel"
        assert result["location"] == "home"
        assert result["timing"] == "location"

    def test_cancel_reminder(self):
        sr = ShortcutResolver()
        result = sr.resolve("取消提醒")
        assert result is not None
        assert result["action"] == "cancel_last"


class TestPrefixMatch:
    def test_snooze_with_params(self):
        sr = ShortcutResolver()
        result = sr.resolve("延迟10分钟")
        assert result is not None
        assert result["action"] == "snooze"
        assert result["delay_seconds"] == 600

    def test_snooze_half_hour(self):
        sr = ShortcutResolver()
        result = sr.resolve("延迟半小时")
        assert result is not None
        assert result["delay_seconds"] == 1800


class TestNoMatchFallback:
    def test_complex_query_returns_none(self):
        sr = ShortcutResolver()
        result = sr.resolve("帮我查一下明天的天气")
        assert result is None


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("10分钟") == 600
        assert parse_duration("5分") == 300

    def test_half_hour(self):
        assert parse_duration("半小时") == 1800

    def test_hour(self):
        assert parse_duration("1小时") == 3600

    def test_invalid(self):
        assert parse_duration("abc") is None
```

- [ ] **步骤 3：实现 shortcuts.py**

```python
"""快捷指令解析器——高频场景不走 LLM 流水线."""
import re
import tomllib
from pathlib import Path


_SHORTCUTS_PATH = Path(__file__).resolve().parents[2] / "config" / "shortcuts.toml"


def parse_duration(s: str) -> int | None:
    """解析中文时长字符串为秒数。"""
    s = s.strip()
    if s == "半小时":
        return 1800
    m = re.match(r"(\d+)\s*(小时|分钟|分)", s)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            return num * 3600
        return num * 60
    return None


def parse_time(s: str) -> str | None:
    """解析中文时间字符串为 ISO 时间字符串 HH:MM:SS。
    支持："3点"→"15:00", "下午3点"→"15:00", "上午9点"→"09:00"。
    上/下午缺省时 < 8 算下午。"""
    s = s.strip()
    m = re.match(r"(上午|下午)?(\d+)点", s)
    if not m:
        return None
    am_pm = m.group(1)
    hour = int(m.group(2))
    if am_pm == "上午" and hour == 12:
        hour = 0
    elif am_pm == "下午" and hour != 12:
        hour += 12
    elif am_pm is None:
        # 缺省：< 8 算下午
        if hour < 8:
            hour += 12
    return f"{hour:02d}:00:00"


class ShortcutResolver:
    def __init__(self):
        self._shortcuts: list[dict] = []
        self._load()

    def _load(self):
        try:
            with open(_SHORTCUTS_PATH, "rb") as f:
                data = tomllib.load(f)
            self._shortcuts = data.get("shortcuts", [])
        except (OSError, tomllib.TOMLDecodeError):
            self._shortcuts = []

    def resolve(self, query: str) -> dict | None:
        # 按 (匹配长度降序, priority 降序) 排列
        candidates = []
        for sc in self._shortcuts:
            for pat in sc.get("patterns", []):
                if query == pat:
                    candidates.append((len(pat), sc.get("priority", 0), sc, pat, query[len(pat):].strip(), True))
                elif query.startswith(pat):
                    candidates.append((len(pat), sc.get("priority", 0), sc, pat, query[len(pat):].strip(), False))
        if not candidates:
            return None
        # 选最优：最长前缀 + 最高 priority
        candidates.sort(key=lambda x: (-x[0], -x[1]))
        _, _, sc, _, params, exact = candidates[0]
        return self._to_decision(sc, params)

    @staticmethod
    def _to_decision(shortcut: dict, params: str) -> dict:
        sc_type = shortcut.get("type", "")
        if sc_type == "travel":
            decision = {
                "should_remind": True,
                "timing": "location",
                "type": "travel",
                "location": shortcut.get("location", ""),
                "reminder_content": {
                    "speakable_text": shortcut.get("speakable_text", ""),
                    "display_text": shortcut.get("display_text", ""),
                    "detailed": f"提醒：到达{shortcut.get('location', '')}时",
                },
            }
            # params 含时间参数时 → 复合触发
            if params:
                parsed_time = parse_time(params)
                if parsed_time:
                    decision["timing"] = "location_time"
                    decision["target_time"] = parsed_time
            return decision
        if sc_type == "action":
            action = shortcut.get("action", "")
            if action == "cancel_last":
                return {"should_remind": False, "timing": "skip", "action": "cancel_last"}
            if action == "snooze":
                secs = parse_duration(params) if params else 300
                return {
                    "should_remind": True,
                    "timing": "delay",
                    "delay_seconds": secs,
                    "type": "other",
                    "reminder_content": {
                        "speakable_text": shortcut.get("speakable_text", ""),
                        "display_text": shortcut.get("display_text", ""),
                        "detailed": f"已延迟{secs//60}分钟",
                    },
                }
        return {"should_remind": True, "timing": "now"}
```

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/test_shortcuts.py -v
```

- [ ] **步骤 5：Commit**

```bash
git add config/shortcuts.toml app/agents/shortcuts.py tests/test_shortcuts.py
git commit -m "feat: add ShortcutResolver for high-frequency in-vehicle commands"
```

---

### 任务 5.2：快捷指令入口注入 workflow

**文件：**
- 修改：`app/agents/workflow.py:385-409`（run_with_stages）+ run_stream

- [ ] **步骤 1：在 run_with_stages 入口增加快捷指令检查**

```python
# workflow.py 顶部新增 import
from app.agents.shortcuts import ShortcutResolver

# 在 AgentWorkflow.__init__ 中新增
self._shortcuts = ShortcutResolver()

# 在 run_with_stages() 开头，for node_fn 循环之前：
    async def run_with_stages(self, user_input, driving_context=None, session_id=None):
        stages = WorkflowStages()
        state = { ... }  # 现有代码
        
        # --- 快捷指令检查 ---
        shortcut_decision = self._shortcuts.resolve(user_input)
        if shortcut_decision:
            if driving_context:
                constraints = apply_rules(driving_context)
                shortcut_decision = postprocess_decision(shortcut_decision, constraints)
            # 直接走 Execution Agent
            state["decision"] = shortcut_decision
            state["stages"] = stages
            # 跳过 Context/Task/Strategy
            exec_result = await self._execution_node(state)
            state.update(exec_result)
            result = state.get("result") or "处理完成"
            event_id = state.get("event_id")
            if session_id:
                self._conversations.add_turn(session_id, user_input, shortcut_decision, result)
            return result, event_id, stages
        
        # 否则正常走四阶段流水线
        for node_fn in self._nodes:
            ...

    # run_stream 同样在开头加：
    async def run_stream(self, ...):
        shortcut_decision = self._shortcuts.resolve(user_input)
        if shortcut_decision:
            if driving_context:
                constraints = apply_rules(driving_context)
                shortcut_decision = postprocess_decision(shortcut_decision, constraints)
            state["decision"] = shortcut_decision
            exec_result = await self._execution_node(state)
            state.update(exec_result)
            done_data = { ... }  # 同原有逻辑
            events.append({"event": "done", "data": done_data})  # 注意：list append，非 yield
            return events
        
        # 否则正常流式
        ...
```

- [ ] **步骤 2：运行全部测试**

```bash
uv run pytest tests/ -v
```

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "feat: inject shortcut resolver before full pipeline in workflow"
```

---

## 收尾任务

### 任务 F.1：移除 processQuery GraphQL mutation（替换为 SSE）

**文件：**
- 修改：`app/api/graphql_schema.py`（移除 ProcessQueryInput/ProcessQueryResult）
- 修改：`app/api/resolvers/mutation.py`（移除 process_query resolver）

- [ ] **步骤 1：移除相关类型和 resolver**

从 `graphql_schema.py` 移除 `ProcessQueryInput`、`ProcessQueryResult`（保留作为内部类型导出供 stream.py 使用）。

从 `mutation.py` 移除 `process_query` 方法，移除相应 import。

- [ ] **步骤 2：更新 WebUI**

修改 `webui/app.js`：将 GraphQL mutation `processQuery` 调用改为 SSE `EventSource`。核心改动：

```javascript
// 旧：fetch POST /graphql { query: "mutation { processQuery(...) }" }
// 新：
function sendQuery(query) {
    const params = new URLSearchParams({ query, ...getContextParams() });
    const es = new EventSource(`/query/stream?${params}`);  // 实际用 POST
    // 更好的方式：用 fetch + ReadableStream（EventSource 不支持 POST）
    fetch("/query/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, context: getDrivingContext(), current_user: "default" }),
    }).then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        // 逐行解析 SSE 事件...
        reader.read().then(function process({done, value}) {
            if (done) return;
            const lines = decoder.decode(value).split("\n");
            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const data = JSON.parse(line.slice(6));
                    // 更新 UI...
                }
            }
            reader.read().then(process);
        });
    });
}
```

具体修改：`webui/app.js` 中 `sendQuery()` 函数（约在 L150-200），将 `fetch("/graphql", { body: JSON.stringify({query: gql}) })` 替换为上述 SSE fetch 逻辑。

- [ ] **步骤 3：更新测试**

将 `test_graphql.py` 中 processQuery 测试迁移到 SSE 集成测试。

- [ ] **步骤 4：运行 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 5：Commit**

```bash
git add app/api/graphql_schema.py app/api/resolvers/mutation.py webui/app.js tests/test_graphql.py
git commit -m "refactor: replace processQuery mutation with SSE /query/stream endpoint"
```

---

## 实现顺序总结

```
1.1 (outputs.py) → 1.2 (prompts) → 1.4 (workflow OutputRouter)
  ↓
2.1 (pending.py) → 2.2 (workflow PendingReminder) → 2.3 (mutations)
  ↓
3.1 (run_stream) → 3.2 (SSE endpoint)
  ↓
4.1 (conversation.py) → 4.2 (workflow + conversation_history) → 4.3 (closeSession)
  ↓
5.1 (shortcuts.py + .toml) → 5.2 (workflow shortcut check)
  ↓
F.1 (移除 processQuery → SSE 迁移)
```

每个任务间可通过 commit 隔离，失败可逐个回滚。
