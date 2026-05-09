# 车载交互优化设计规格

日期：2026-05-09
状态：待审查

## 概述

当前知行车秘系统在决策引擎层（规则引擎、MemoryBank、四Agent流水线）已适配车载场景，
但在交互通道层存在六个关键缺失。本设计在现有决策引擎之上补齐交互层，
不改动核心流水线架构。

### 问题清单

| ID | 问题 | 严重度 |
|----|------|--------|
| P0 | 语音输出适配：无 speakable_text/display_text 分化 | 安全相关 |
| P0 | 主动触发：无延迟提醒队列与触发机制 | 安全相关 |
| P2 | 流式响应：全同步阻塞，无进度推送 | 体验 |
| P3 | 多轮对话：无 session 管理，无指代消解 | 体验 |
| P4 | 快捷指令：高频场景走完整流水线 | 体验+可靠性 |
| P5 | 通道抽象：5种标签散落各处无统一枚举 | 架构 |
| P6 | 打断分级：only_urgent 仅二元决策 | 架构 |

### 设计决策

- **TTS 边界**：系统仅生成 speakable_text（≤15字，无标点），TTS 引擎为车机端职责
- **主动触发**：车机端轮询模式（pollPendingReminders mutation），非服务端定时器
- **流式协议**：REST SSE 端点，非 GraphQL Subscription
- **向后兼容**：不保留。REST SSE `/query/stream` 为唯一查询入口。原 GraphQL `processQuery` mutation 移除。`ProcessQueryInput` 类型保留为 SSE 请求 body 的 JSON schema（非 GraphQL 类型），`ProcessQueryResult` 作为 SSE `done` 事件的 data schema。其余 mutation（submitFeedback、exportData 等）不变。
  - 影响：`tests/test_graphql.py` 中的 processQuery 测试需重写为 SSE 集成测试。WebUI（`webui/app.js`）需改用 EventSource 连接 `/query/stream`。
- **实现顺序**：模块1 → 模块2 → 模块3/4/5。
  模块3/4/5 均改动 `workflow.py`，存在文件级冲突。并行实现需：
  (a) 将 workflow.py 拆分为独立模块文件（推荐），或
  (b) 顺序实现模块3→4→5，每步合并后再进下一步

## 模块1：多格式输出 + 通道路由 + 打断分级

覆盖 P0 / P5 / P6。

### 新增类型

```python
# app/agents/outputs.py（新文件）
from dataclasses import dataclass
from enum import Enum

class OutputChannel(Enum):
    AUDIO = "audio"
    VISUAL = "visual"
    DETAILED = "detailed"

class InterruptLevel(Enum):
    NORMAL = 0           # 不打断
    URGENT_NORMAL = 1    # 紧急，可缓3s
    URGENT_IMMEDIATE = 2 # 立即打断，ducking

@dataclass
class ReminderContent:
    speakable_text: str     # ≤15字，无标点，TTS 友好
    display_text: str       # ≤20字，HUD 可扫读
    detailed: str              # 完整文本（停车时查看，纯字符串非 dict）
    channel: OutputChannel
    interrupt_level: InterruptLevel
```

### OutputRouter 逻辑

```
输入：decision_dict, scenario, rules_result
输出：ReminderContent

流程：
1. **提取 speakable_text / display_text**：
   Strategy Agent 输出 decision JSON 中新增 `reminder_content` 子对象：
   ```json
   {
     "reminder_content": {
       "speakable_text": "3点，公司3楼，会议",   // ≤15字，无标点，TTS友好
       "display_text": "会议 · 15:00 · 公司3F",   // ≤20字，HUD可扫读
       "detailed": "会议提醒：下午3点公司3楼会议室"
     }
   }
   ```
   若 `decision.reminder_content` 不存在或其 `speakable_text` 为空 → OutputRouter fallback：从 `decision.reminder_content.detailed`（str）截断至 ≤15/≤20 字，去标点。若 `detailed` 亦为空，兜底文本 `"提醒"`。
2. **决定 channel**：rules_result.allowed_channels 取第一优先；空集 → VISUAL。
   注：`rules.toml` 保持字符串 `"audio"/"visual"/"detailed"`。`rules.py` 在 `format_constraints()` 中将字符串转为 `OutputChannel` 枚举。
3. **决定 interrupt_level**：
   - decision.is_emergency == true（LLM 判定为紧急事件）→ IMMEDIATE (2)
   - rules_result.only_urgent == true（规则引擎疲劳/过载触发）→ URGENT_NORMAL (1)
   - 其他 → NORMAL (0)

   注：`is_emergency` 为 Strategy Agent 新增输出字段（boolean），由 LLM 根据事件语义判断是否为紧急事件（急救、儿童遗留、事故预警等），与规则引擎的 `only_urgent`（由疲劳/过载场景触发）互不重叠。
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/agents/outputs.py` | **新文件**。OutputRouter + ReminderContent + 枚举 |
| `app/agents/prompts.py` | Strategy Agent 提示词增加 speakable_text/display_text 生成要求 |
| `app/agents/rules.py` | allowed_channels 改用 OutputChannel 枚举（去字符串） |
| `app/agents/workflow.py` | Execution Agent 后处理调用 `OutputRouter.route()` |
| `app/api/graphql_schema.py` | 模块1暂不改 GraphQL schema。processQuery 移除延期至模块3（SSE 上线后统一迁移） |
| `config/rules.toml` | 兼容，无需改动 |

### 数据流

```
Strategy LLM 输出 decision_dict
        ↓
apply_rules() → rules_result (allowed_channels, postpone, only_urgent)
        ↓
postprocess_decision() → 覆盖 decision_dict
        ↓
OutputRouter.route(decision_dict, scenario, rules_result) → ReminderContent
        ↓
ProcessQueryResult { speakable_text, display_text, detailed, channel, interrupt_level }
```

## 模块2：主动触发框架

覆盖 P0。

### 数据模型

```python
@dataclass
class PendingReminder:
    id: str
    event_id: str
    content: ReminderContent       # 复用模块1输出
    trigger_type: str              # "location" | "time" | "context"
    trigger_target: dict           # {latitude, longitude, address} 或 {time: ISO}
    trigger_text: str              # 人类可读触发条件，如"到达公司附近时"
    status: str                    # "pending" | "triggered" | "cancelled"
    created_at: str               # ISO 8601
    ttl_seconds: int              # 超时自动取消

# 存储：data/users/{user_id}/pending_reminders.toml
# 使用 TOMLStore（现有工具），列表模式 append/read
# id 生成：uuid4()
# 并发安全：TOMLStore 已有 per-file asyncio.Lock，无需额外锁
# cancel_last 行为：移除最近一条 pending reminder；无 pending → no-op，返回 {"cancelled": false}

# TriggeredReminder = PendingReminder 的子集视图，仅返回已触发的：
# { id, content (ReminderContent), triggered_at }
```

### API

| Mutation | 输入 | 返回 |
|----------|------|------|
| `pollPendingReminders` | currentUser, context: DrivingContextInput | [TriggeredReminder] |
| `cancelPendingReminder` | pendingReminderId, currentUser | bool |
| `getPendingReminders` | currentUser | [PendingReminder] |

### 触发评估

```
pollPendingReminders(context):
  for each pending reminder:
    1. 检查 TTL：now - created_at > ttl_seconds → cancel
       (ttl_seconds 默认值：location 类型 3600s，time 类型 target_time + 1800s)
    2. trigger_type == "location":
       - 距离 < 500m → trigger
        - 场景 == "parked" → 无条件立即 trigger（不等距离检查）
    3. trigger_type == "time":
       - now >= target_time → trigger
    4. triggered: status → "triggered", 加入返回列表

已知限制：TTL 清理仅在 pollPendingReminders 触发时执行（惰性）。若用户停止轮询，pending_reminders.toml 不会自动收缩。后续版本可加后台定期清理。
```

### 与 Execution Agent 集成

`map_trigger_type()` / `map_trigger_target()` 为 Execution Agent 内部调用之辅助函数，从 decision JSON + driving_context 映射出 PendingReminder 的触发字段：

| decision 字段 | → trigger_type | → trigger_target |
|---------------|----------------|------------------|
| `task.type == "travel"` + `destination` | `"location"` | `{latitude, longitude}` 从 driving_context.destination 获取 |
| `timing` 包含 ISO 时间 | `"time"` | `{time: ISO}` |
| `timing == "location_time"` | `"time"` + `"location"` | 拆为两个独立 PendingReminder（一个 location，一个 time）。任一触发即提醒。 |
| `timing == "delay"` 无位置/时间信息 | `"context"` | `{previous_scenario: 入队时的 scenario}`。仅当 scenario 切换时触发。TTL: 3600s |

```
Execution Agent:
  # 处理 action 指令
  if decision.get("action") == "cancel_last":
    pm = PendingReminderManager(user_id)
    cancelled = pm.cancel_last()
    return ExecutionResult(status="cancelled", cancelled=cancelled)

  # 处理位置触发（timing == "location" || "location_time"）与延迟触发（timing == "delay"）
  if decision.get("timing") in ("delay", "location", "location_time") or postprocess_decision() returns postpone==True:
    pm = PendingReminderManager(user_id)
    pm.add(PendingReminder(
      content=output_router.route(decision, ...),
      trigger_type=map_trigger_type(decision),
      trigger_target=map_trigger_target(decision, driving_context),
      ...
    ))
    return { "pending": True, "pending_reminder_id": pm_id }
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/agents/pending.py` | **新文件**。PendingReminderManager：增删查 + 触发评估 + TTL 清理 |
| `app/agents/workflow.py` | Execution Agent：timing=delay → PendingReminderManager.add() |
| `app/api/resolvers/mutation.py` | 新增 3 个 resolver |
| `app/api/graphql_schema.py` | 新增 TriggeredReminder / PendingReminder GQL 类型 + input |

## 模块3：流式响应

覆盖 P2。

### 端点

```
POST /query/stream
Body: ProcessQueryInput (Python dataclass, 原 processQuery mutation 输入 schema，迁移至 app/schemas/query.py)
Response: text/event-stream (SSE)
```

### SSE 事件

| 事件 | data | 触发时机 |
|------|------|----------|
| `stage_start` | `{"stage":"context"\|"task"\|"strategy"\|"execution"}` | 阶段开始 |
| `context_done` | `{"context":{...},"related_events":5}` | Context 完成 |
| `task_done` | `{"tasks":[...],"count":2}` | Task 完成 |
| `decision` | `{"should_remind":true,"type":"meeting"}` | Strategy 完成 |
| `done` | 见下方 ProcessQueryResult | 全部完成 |
| `error` | `{"code":"...","message":"..."}` | 任何阶段失败，连接关闭 |

`done` 事件 data = ProcessQueryResult schema：
```json
// 立即提醒 (status: "delivered")
{"status":"delivered","event_id":"...","session_id":"...","result":{"speakable_text":"...","display_text":"...","detailed":"...","channel":"audio","interrupt_level":0}}
// 延迟提醒入队 (status: "pending")
{"status":"pending","event_id":"...","session_id":"...","pending_reminder_id":"...","trigger_text":"到达公司附近时"}
// 取消/抑制 (status: "suppressed")
{"status":"suppressed","event_id":"...","session_id":"...","reason":"安全规则禁止发送"}
```

### 实现

```python
# app/agents/workflow.py
async def run_stream(query: str, driving_context: dict, session_id: str = None):
    """SSE 生成器。yield 阶段事件。"""
    yield sse_event("stage_start", {"stage": "context"})
    context = await context_agent.run(query, driving_context)
    yield sse_event("context_done", {"context": context, "related_events": ...})

    yield sse_event("stage_start", {"stage": "task"})
    tasks = await task_agent.run(query, context)
    yield sse_event("task_done", {"tasks": tasks, "count": len(tasks)})

    yield sse_event("stage_start", {"stage": "strategy"})
    decision = await strategy_agent.run(context, tasks)
    yield sse_event("decision", {"should_remind": decision["should_remind"], ...})

    yield sse_event("stage_start", {"stage": "execution"})
    result = await execution_agent.run(...)
    done_data = {"event_id": result.event_id, "session_id": session_id}
    if result.pending:
        done_data["status"] = "pending"
        done_data["pending_reminder_id"] = result.pending_reminder_id
        done_data["trigger_text"] = result.trigger_text
    elif result.suppressed:
        done_data["status"] = "suppressed"
        done_data["reason"] = result.reason
    else:
        done_data["status"] = "delivered"
        done_data["result"] = result.content  # ReminderContent
    yield sse_event("done", done_data)
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/agents/workflow.py` | 新增 `run_stream()` 生成器 |
| `app/api/stream.py` | **新文件**。SSE endpoint + StreamingResponse |
| `app/api/main.py` | 注册 `/query/stream` 路由 |

## 模块4：多轮对话

覆盖 P3。

### 数据模型

```python
@dataclass
class ConversationTurn:
    turn_id: int
    query: str
    response_summary: str         # 系统响应的简短摘要
    decision_snapshot: dict       # {should_remind, type, entities}
    timestamp: str

@dataclass
class Conversation:
    session_id: str
    user_id: str
    created_at: str
    last_activity: str
    turns: list[ConversationTurn]  # 保留最近 10 轮

# 存储：内存 dict[session_id → Conversation]。纯短期。超时 30min 自动清理。
# 已知限制：服务重启丢失所有会话。当前设计不持久化 conversation（YAGNI）。
```

### Context Agent 增强

在 Context Agent 输入中增加 `conversation_history` 字段。注入 Context prompt 的格式（JSON 序列化后拼入）：

```json
// 注入到 Context Agent system prompt 的 ## 对话历史 节
[
  {"turn": 1, "user": "提醒我到公司", "assistant_summary": "已设置到达公司时的提醒", "intent": {"type": "travel", "target": "公司"}},
  {"turn": 2, "user": "刚才那个什么时候？", "assistant_summary": null}  // 当前轮，assistant_summary 为空
]
```

LLM 需基于此理解指代（"刚才那个"→ turn 1 的 intent）。最近 5 轮包含在内，超过截断最早轮次。

### API 变更

`ProcessQueryInput` 和 `ProcessQueryResult` 不再作为 GraphQL 类型存在——转为 SSE 端点的 JSON schema（定义于 `app/schemas/`）。GraphQL 层仅保留：

| 变更 | 说明 |
|------|------|
| `mutation processQuery` 移除 | 由 `POST /query/stream` 替代 |
| SSE 请求 body 使用 `ProcessQueryInput` JSON schema | 增加可选 `session_id` 字段 |
| SSE `done` 事件 data 使用 `ProcessQueryResult` JSON schema | 增加 `session_id` 字段 |
| 新增 `closeSession(sessionId)` mutation | 关闭会话，清除内存 turns |

### 会话生命周期

- **创建**：首次 processQuery 无 session_id → 自动创建
- **追加**：每次 processQuery → 追加 turn，保留最近 10 轮
- **超时**：`last_activity > 30min` → 惰性检查（每次 processQuery 时清理自身会话）+ 后台定期扫描（每 5 分钟清理所有超时会话）
- **关闭**：`closeSession` → 清除内存中的 turns，释放会话。PendingReminder 不受影响（其生命周期独立于会话）。

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/agents/conversation.py` | **新文件**。ConversationManager |
| `app/agents/workflow.py` | Context Agent 准备阶段注入 conversation_history |
| `app/schemas/query.py` | ProcessQueryInput + session_id、ProcessQueryResult + session_id |
| `app/api/resolvers/mutation.py` | 新增 closeSession |
| `app/api/graphql_schema.py` | 新增 closeSession mutation + SessionResult 类型 |

## 模块5：快捷指令

覆盖 P4。

### 指令表

`config/shortcuts.toml`：

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
# 前缀匹配例："延迟10分钟" → pat="延迟", params="10分钟" → delay_seconds=600
```

### 匹配算法

```
resolve_shortcut(query):
  1. shortcuts = load_shortcuts()  # TOML 加载，启动时缓存
  2. for sc in shortcuts sorted by (-len(pat), -priority):  # 先按匹配长度降序，再按 priority 降序
     for pat in sc.patterns:
       if query == pat → 返回预构建 decision
       if query.startswith(pat):
         params = query[len(pat):].strip()
         # 例："延迟10分钟" → pat="延迟", params="10分钟"
         # → decision.timing.delay_minutes = parse_duration(params)
         # 例："提醒到公司3点" → pat="提醒到公司", params="3点"
         # → decision.target_time = parse_time(params)
         return sc.to_decision(params=params)
  3. return None → 回退完整流水线
```

### 集成点

```python
# app/agents/workflow.py run_with_stages() + run_stream() 入口处
result = resolve_shortcut(query)
if result:
    # 快捷路径仍需过安全约束。跳过 Context/Task/Strategy LLM。
    if driving_context:
        rules_result = apply_rules(driving_context_scenario, result)
        result = postprocess_decision(result, rules_result)
    return execution_agent.run(result)
# 否则正常走四阶段流水线
```

`to_decision(params)` 映射规则：从 TOML shortcut 条目生成 decision dict。

```python
def to_decision(self, params: str = "") -> dict:
    if self.type == "travel":
        decision = {
            "should_remind": True,
            "timing": "location",
            "type": "travel", "location": self.location,
            "reminder_content": {
                "speakable_text": self.speakable_text,
                "display_text": self.display_text,
                "detailed": f"提醒：到达{self.location}时"
            }
        }
        # params 为时间参数时，追加时间触发："提醒到公司3点"
        if params:
            parsed_time = parse_time(params)
            if parsed_time:
                decision["timing"] = "location_time"  # 复合触发
                decision["target_time"] = parsed_time
        return decision
    if self.type == "action":
        if self.action == "cancel_last":
            return {"should_remind": False, "timing": "skip", "action": "cancel_last"}
        if self.action == "snooze":
            secs = parse_duration(params) if params else 300
            return {"should_remind": True, "timing": "delay",
                    "delay_seconds": secs, "type": "other"}
```

参数解析函数（仅支持中文数字 + 时间格式。解析失败 → 回退 LLM 流水线）：

```python
def parse_duration(s: str) -> int | None:
    # 支持格式："10分钟"→600, "半小时"→1800, "1小时"→3600, "5分"→300
    # 先特殊匹配 "半小时"，再正则 r'(\d+)\s*(分钟|分|小时)'
    # 不支持组合（"半小时20分钟"→回退 LLM）。返回 None 表示无法解析。

def parse_time(s: str) -> str | None:
    # 支持格式："3点"→"15:00", "下午3点"→"15:00", "上午9点"→"09:00"
    # 正则：r'(上午|下午)?(\d+)点'。缺省上/下午按 24h 推断（<8 算下午）。
    # 返回 None 表示无法解析。
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `config/shortcuts.toml` | **新文件**。快捷指令表 |
| `app/agents/shortcuts.py` | **新文件**。ShortcutResolver |
| `app/agents/workflow.py` | run_with_stages() + run_stream() 入口处检查 |

## 文件变更总览

| 类型 | 文件 | 模块 |
|------|------|------|
| 新增 | `app/agents/outputs.py` | 1 |
| 新增 | `app/agents/pending.py` | 2 |
| 新增 | `app/api/stream.py` | 3 |
| 新增 | `app/agents/conversation.py` | 4 |
| 新增 | `app/agents/shortcuts.py` | 5 |
| 新增 | `config/shortcuts.toml` | 5 |
| 新增 | `app/schemas/query.py` | 1,4 (ProcessQueryInput/Result 转为 Pydantic schema，用于 SSE 请求/响应 JSON) |
| 修改 | `app/agents/prompts.py` | 1 |
| 修改 | `app/agents/rules.py` | 1 |
| 修改 | `app/agents/workflow.py` | 1,2,3,4,5 |
| 移除 | `mutation processQuery` 相关 GraphQL 类型及 resolver | 1 |
| 修改 | `app/api/graphql_schema.py` | 模块3时移除 processQuery。模块4新增 closeSession |
| 修改 | `app/api/resolvers/mutation.py` | 移除 processQuery，新增 pending + session mutations |
| 修改 | `app/api/main.py` | 注册 SSE 路由 |

## 测试计划

| 模块 | 测试重点 |
|------|----------|
| 1 | OutputRouter 各通道、打断级别、speakable_text 截断规则（含边界：英文/纯数字输入）、LLM 输出与 fallback 路径 |
| 2 | PendingReminder CRUD、位置触发（Haversine）、时间触发、TTL 过期、并发轮询 |
| 3 | SSE 事件顺序、异常中断（模拟 LLM 失败）、done 事件字段完整性 |
| 4 | 会话创建/追加/超时/关闭、conversation_history 注入 Context prompt、指代消解集成测试 |
| 5 | 精确匹配、前缀匹配、参数提取、未命中回退、多 pattern 冲突 priority 选择 |
