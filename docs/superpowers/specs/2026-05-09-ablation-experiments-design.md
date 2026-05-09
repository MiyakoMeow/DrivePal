# DrivePal-2 消融实验设计

> 状态：已通过自审，待用户审查 | 日期：2026-05-09

## 一、目的

为毕业论文实验章节设计消融实验（ablation study），验证 DrivePal-2 系统各组件的独立贡献。

核心研究问题：

1. **安全性**：规则引擎 + 概率推断对安全决策的贡献多大？
2. **架构**：四 Agent 流水线 vs 单 LLM 调用，决策质量差异多大？
3. **个性化**：反馈学习机制能否使系统逐步贴近用户真实偏好？

## 二、实验总体架构

```
                    ┌─────────────────────────────┐
                    │    场景合成器 (LLM)          │
                    │  按维度组合生成测试场景       │
                    └─────────────┬───────────────┘
                                  │ N 个场景 JSON
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
    ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐
    │  安全性组        │  │  架构组       │  │  个性化组        │
    │  Full/-Rules/-Prob│  │  Full vs 单LLM│  │  Full/-Feedback  │
    └────────┬────────┘  └──────┬───────┘  └────────┬────────┘
              │                 │                    │
              ▼                 ▼                    ▼
    ┌─────────────────────────────────────────────────┐
    │           LLM-as-Judge 统一评分                  │
    │  (人工标注 ~50 样本校准，批量自动评分)           │
    └─────────────────────────┬───────────────────────┘
                              ▼
    ┌─────────────────────────────────────────────────┐
    │            统计分析 + 可视化                     │
    │  安全合规率 / 决策质量分 / 偏好匹配率           │
    └─────────────────────────────────────────────────┘
```

## 三、场景合成

### 3.1 维度空间

| 维度 | 取值 | 说明 |
|------|------|------|
| scenario | highway / city_driving / traffic_jam / parked | 驾驶场景 |
| fatigue_level | 0.1 / 0.5 / 0.9 | 疲劳度低中高 |
| workload | low / normal / overloaded | 认知负荷 |
| task_type | meeting / travel / shopping / contact / other | 事件类型 |
| has_passengers | true / false | 乘客在场 |

全组合 4×3×3×5×2 = 360 场景。精选 ~100-150 场景，保证每组实验有足够样本同时避免冗余。

### 3.2 TestScenario 数据结构

```python
@dataclass
class TestScenario:
    id: str
    driving_context: dict        # 完整 DrivingContext
    user_query: str              # 用户输入
    expected_decision: dict      # 期望决策（必含字段：should_remind, channel, content, is_urgent）
    expected_task_type: str      # 期望事件类型
    safety_relevant: bool        # 是否涉及安全约束（合成时自动判定：scenario in [highway,city_driving] or fatigue>0.7 or workload=overloaded → True）
    scenario_type: str           # 场景类型标签
```

### 3.3 合成方法

- 调用 ChatModel（JSON mode），按维度组合批量生成
- 每个场景含 driving_context + user_query + expected_decision
- 缓存到 `data/experiments/scenarios.jsonl`，支持增量合成
- 固定 seed 保证可复现

### 3.4 场景精选策略

从 360 全组合中精选 ~120 场景：

1. **安全关键场景**（~50 个）：从 highway/fatigue>0.7/overloaded 条件行中按 4.1 场景表分层抽样，保证每行配额
2. **多样化场景**（~50 个）：从非安全关键组合中分层随机抽样，覆盖所有 scenario × task_type 组合
3. **个性化组场景**（~20 个）：从多样化场景中选取 meeting/travel/shopping/contact/other 各 4 个

筛选用 `ABLATION_SEED` 固定随机种子，保证可复现。

## 四、三组实验详设

### 4.1 安全性组

**研究问题**：规则引擎和概率推断各自对安全决策的贡献。

**变体**：

| 变体 | 规则引擎 | 概率推断 | 其余组件 |
|------|:-------:|:-------:|---------|
| Full | ✅ | ✅ | 四Agent + Memory + Feedback |
| -Rules | ❌ | ✅ | 同上 |
| -Prob | ✅ | ❌ | 同上 |

**测试场景**：仅安全关键场景，总计 50 个。

| 场景条件 | 覆盖规则 | 场景数 |
|---------|---------|--------|
| highway + 各疲劳度 + 各任务 | highway_audio_only | 15 |
| fatigue > 0.7 + 各场景 + 各任务 | fatigue_suppress | 15 |
| workload=overloaded + 各场景 + 各任务 | overloaded_postpone | 10 |
| city_driving + 正常状态 + 各任务 | city_driving_limit | 10（从 city_driving + fatigue≤0.7 + workload∈[low,normal] + passenger∈[true,false] + 5 task_types 组合中随机抽取） |

**评估指标**：

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 安全合规率 | 决策是否违反安全约束 | Judge 对比决策 vs 规则要求 |
| 规则拦截率 | Full 中规则纠正 LLM 输出的比例 | postprocess_decision 修改数 / 总数 |
| 误拦率 | 规则错误拦截合理决策的比例 | 校准阶段人工标注判断（一次性），运行时 Judge 自动评分替代 |
| 决策综合质量 | Judge 1-5 分 | 安全性 + 合理性 + 用户体验 |

### 4.2 架构组

**研究问题**：四 Agent 结构化流水线 vs 单 LLM 调用，决策质量差异。

**变体**：

| 变体 | 说明 |
|------|------|
| Full | 四阶段流水线（Context → Task → Strategy → Execution） |
| SingleLLM | 单次 LLM 调用，输出结构含 context+task+decision（三字段合并，详见 §4.2.1），绕过规则后处理 |

**测试场景**：~50 个多样化场景，覆盖所有 scenario × task_type 组合，不含安全关键条件（fatigue ≤ 0.7, workload ≠ overloaded, scenario ≠ highway）。

**评估指标**：

| 指标 | 定义 |
|------|------|
| 决策质量分 | Judge 1-5 分，综合考量合理性、上下文理解、任务归因 |
| JSON 结构合规率 | 输出是否包含所有必需字段、类型正确、格式合法 |
| 各阶段中间质量 | Context/Task/Strategy 各阶段 Judge 独立评分 |
| 端到端延迟 | processQuery 总耗时，对比单 LLM 的额外开销 |

### 4.2.1 SingleLLM Prompt 设计

单 LLM 变体需在一个 prompt 内完成 Context + Task + Strategy 三阶段输出。
Prompt 合并三个 Agent 的职责，要求输出结构为：

```json
{
  "context": { /* 同Context Agent输出schema */ },
  "task": { /* 同Task Agent输出schema */ },
  "decision": { /* 同Strategy Agent输出schema */ }
}
```

与四阶段 Full 变体输出完全相同的 JSON 结构，确保 Judge 盲评可比。
**绕过规则后处理**：单 LLM 输出直接作为最终决策，不经 `postprocess_decision()`。此设计保证架构对比的纯净性（"是否分阶段 vs 是否加规则"不混杂）。

### 4.3 个性化组

**研究问题**：反馈学习机制能否使系统决策逐步贴近用户真实偏好。

**变体**：

| 变体 | 反馈学习 | 权重 |
|------|:-------:|------|
| Full | ✅ | 动态调整（初始 0.5，±0.1 per 反馈） |
| -Feedback | ❌ | 固定 0.5（均等） |

**实验设计**：模拟同一用户 20 轮交互序列。

**测试场景**：从场景池中抽取 20 个非安全关键场景（覆盖 meeting/travel/shopping/contact/other 各 4 个），
每轮按序使用一个场景。场景本身不变，用户偏好阶段性地切换。

```
轮次 1-5  ：偏好 → 高频率提醒，偏好 meeting/travel 类型
轮次 6-10 ：偏好 → 静默（仅 urgent），偏好 ignore 所有非紧急提醒
轮次 11-15：偏好 → 详细视觉提醒，偏好 shopping/contact 类型
轮次 16-20：偏好 → 混合（恢复默认），无明确类型偏好
```

每轮：系统生成决策 → 按当前阶段偏好模拟反馈 → Full 更新权重。

**反馈调用流程**（每轮执行）：
1. `ablation_runner` 直接调用 `AgentWorkflow.run_with_stages()` 获得 `event_id` + 决策（**进程内调用，不启动 HTTP 服务**）
2. 反馈模拟函数根据决策与当前阶段偏好判定 `action`（accept/ignore）
3. 直接调用解析器层的 `submit_feedback_impl(event_id, action, user_id)` 触发权重更新（绕过 GraphQL 层，避免 HTTP 依赖）

所有变体运行均在进程内完成，不依赖 FastAPI 服务栈。

**反馈模拟函数**：根据生成决策是否匹配当前阶段偏好判定 accept/ignore。

| 阶段 | 判定规则 |
|------|---------|
| 阶段 1 (高频率) | 决策 should_remind=true → accept；false → ignore |
| 阶段 2 (静默) | 决策 should_remind=true and is_urgent=true → accept；otherwise ignore |
| 阶段 3 (详细视觉) | 决策 channel=visual and type in [shopping, contact] → accept；otherwise ignore |
| 阶段 4 (混合) | 随机 0.5 概率 accept/ignore（模拟无明确偏好） |

**评估指标**：

| 指标 | 定义 | 量化公式 |
|------|------|---------|
| 偏好匹配率 | 决策与当前阶段期望偏好的一致比例 | 匹配轮数 / 20 |
| 权重收敛速度 | 权重从 0.5 到稳定偏好的轮次数 | 目标类型权重距 ±0.05 内持续 ≥3 轮视为收敛 |
| 收敛稳定性 | 偏好切换后权重振荡幅度 | 切换后连续 5 轮权重的标准差 |
| 过拟合检测 | 最终阶段（混合偏好）下两变体表现差异 | 阶段 4 的偏好匹配率差 (Full - NoFeedback) |

## 五、LLM-as-Judge 评测协议

### 5.1 Judge 配置

- **模型**：优先使用专用 Judge。若环境变量 `JUDGE_MODEL` 已设置（配合 `JUDGE_BASE_URL` / `JUDGE_API_KEY`），使用现有 `get_judge_model()` 获取；否则回退使用 `get_chat_model()`（即 `[model_groups.default]` 配置的模型）。此 fallback 仅用于实验框架（`judge.py` 内实现），不修改现有 `get_judge_model()` 的"未配置即抛异常"行为。
- **模式**：JSON mode
- **温度**：0.0（最大化一致性）
- **重试**：每场景评 3 次，取中位数

### 5.2 盲评机制

- shuffle 变体输出顺序，不标注来源
- Judge prompt 含场景上下文 + 各变体输出 + 评分维度定义
- 输出 JSON：`{safety_score, reasonableness_score, overall_score, violation_flags: [...], explanation}`

**violation_flags 值空间**（对应 7 条规则）：

| Flag | 含义 |
|------|------|
| `channel_violation` | 决策使用了当前场景禁止的提醒渠道 |
| `frequency_violation` | 违反最大提醒频率限制 |
| `non_urgent_during_fatigue` | 驾驶员疲劳时发送非紧急提醒 |
| `remind_during_overload` | 认知过载时仍发送提醒（应 postpone） |
| `missed_urgent` | 应提醒而未提醒（漏报） |

### 5.3 中间阶段独立评分（架构组用）

架构组需对 Full 变体的 Context / Task / Strategy 三阶段分别评分。

| 阶段 | 评分维度 | Judge prompt 要点 |
|------|---------|------------------|
| **Context** | 上下文准确性（1-5） | 时间/位置/交通/偏好/状态推断是否合理、完整 |
| **Task** | 事件归因准确度（1-5） | 事件类型是否正确、置信度是否合理 |
| **Strategy** | 决策合理性（1-5） | should_remind/timing/channel/content 是否合理（忽略规则后处理，评原始 LLM 输出） |

每个中间输出使用独立 Judge prompt，输出 JSON 格式 `{score: int, explanation: str}`。
中间评分不与最终 overall_score 混合——独立报告，定位流水线瓶颈。

### 5.4 校准

- 人工标注 ~50 个场景的期望决策（安全关键 30 + 随机 20）
- 将 50 个场景按 60/40 拆分为校准集（30）和留存集（20，仅用于最终一致率报告，不参与 prompt 调整）
- 计算 Judge 在校准集上的人工一致率（Cohen's κ）
- 若 κ < 0.7：调整 Judge prompt → 重新在 **校准集** 上评分 → 再算 κ。最多 3 轮调整
- 若 3 轮后 κ 仍 < 0.7：换 Judge 模型（用 `[model_groups.smart]` 组），重跑校准流程
- 校准通过后，在留存集上计算最终一致率作为报告值
- 误拦率等需人工判断的指标仅在校准阶段评估，运行时用 Judge 自动评分

## 六、消融开关实现

### 6.1 环境变量控制

消融开关用独立布尔变量，支持任意组合：

| 变量 | 默认 | 说明 |
|------|------|------|
| `ABLATION_DISABLE_RULES` | 0 | 1=跳过规则引擎后处理 |
| `ABLATION_DISABLE_PROB` | 0 | 1=跳过概率推断 |
| `ABLATION_USE_SINGLE_LLM` | 0 | 1=单 LLM 调用替代四 Agent 流水线 |
| `ABLATION_DISABLE_FEEDBACK` | 0 | 1=反馈权重固定 0.5 |
| `ABLATION_SEED` | 42 | 随机种子 |

安全性组运行时：测试框架逐变体设置组合并运行，无需手动切换。
```
safety_group 运行：
  set ABLATION_DISABLE_RULES=0 ABLATION_DISABLE_PROB=0 → run → save Results(Full)
  set ABLATION_DISABLE_RULES=1 ABLATION_DISABLE_PROB=0 → run → save Results(-Rules)
  set ABLATION_DISABLE_RULES=0 ABLATION_DISABLE_PROB=1 → run → save Results(-Prob)
```

### 6.2 代码实现原则

- 环境变量驱动消融行为（§6.1），`ablation_runner` 在每次运行变体前设置对应环境变量
- 环境变量由 `ablation_runner` 在执行前设置，执行后恢复，保证可逆
- 允许的最小生产代码改动：
  - `postprocess_decision()` 新增 `modifications: list[str]` 返回字段（记录被规则修改的字段名），`_execution_node` 将其存入 `WorkflowStages.execution.modifications`。**理由**：规则拦截率是安全性组核心指标，需观测点埋入流水线
  - 其余消融逻辑均通过环境变量控制，不新增参数/分支
- 规则引擎跳过：`postprocess_decision()` 检查 `ABLATION_DISABLE_RULES`，为 1 时透传 LLM 输出
- 概率推断跳过：内部设置 `PROBABILISTIC_INFERENCE_ENABLED=0`
- 单 LLM 路径：`ablation_runner` 检测 `ABLATION_USE_SINGLE_LLM=1`，不调用 `AgentWorkflow.run_with_stages()`，改为直接调用 `ChatModel.generate()`（详见 §4.2.1），且绕过 `postprocess_decision()`（规则后处理仅用于四 Agent 变体，保证架构组对比纯净）
- 反馈关闭：Strategy Agent prompt 注入时检查 `ABLATION_DISABLE_FEEDBACK`，为 1 时跳过权重读取，注入固定权重 0.5

### 6.3 实验间 Memory 状态隔离

三组实验共用同一 MemoryBank，前组写入会影响后组检索结果。隔离策略：

- 每组实验使用独立 `user_id`（如 `experiment-safety` / `experiment-architecture` / `experiment-personalization`）
- 每组实验开始前清空对应用户数据目录（`deleteAllData(user_id)`）
- 个性化组 20 轮交互共用同一 `user_id`（因为需要累积反馈权重），但实验开始前清空上一组残留

**个性化组 Memory 累积处理**：20 轮中 MemoryBank 逐步积累事件——前 5 轮写入的记忆可能影响后 5 轮检索结果。此效应不可消除（真实使用场景中记忆本应累积），但需在分析时量化：
- 记录每轮的 MemoryBank 检索命中数（`search_count` / `search_empty_count`）
- 若后期轮次检索命中明显增多，在分析中标注记忆累积对决策的潜在混杂

### 6.4 执行模式

所有实验变体均在进程内运行，不启动 FastAPI 服务。`ablation_runner` 直接构造组件（`AgentWorkflow` / `ChatModel` / `MemoryModule`），通过函数调用完成测试——零 HTTP 依赖，纯 Python。

## 七、新增文件结构

```
tests/experiments/
├── __init__.py
├── scenario_synthesizer.py    # LLM 场景合成器
├── ablation_runner.py         # 消融变体调度器
├── judge.py                   # LLM-as-Judge 评分
├── safety_group.py            # 安全性组实验
├── architecture_group.py      # 架构组实验
├── personalization_group.py   # 个性化组实验
├── metrics.py                 # 指标计算与统计
├── report.py                  # 结果表格/图表生成
└── conftest.py                # 共享 fixture
```

数据目录：

```
data/experiments/
├── scenarios.jsonl            # 合成场景缓存
└── results/
    ├── safety.jsonl           # 安全性组原始结果
    ├── architecture.jsonl     # 架构组原始结果
    └── personalization.jsonl  # 个性化组原始结果
```

## 八、交付物

1. **`tests/experiments/` 完整代码** —— 可通过 `uv run pytest tests/experiments/ -v --test-llm` 运行
2. **实验数据** —— 合成场景集 + 评分结果（`data/experiments/`）
3. **论文表格** —— 安全合规率对比表、决策质量对比表、偏好匹配率对比表
4. **论文图表** —— 权重收敛曲线、分场景决策质量柱状图、消融贡献瀑布图
5. **实验设计文档** —— 本文件

## 九、关键决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| Judge 模型 | 独立于 Agent（`JUDGE_MODEL`） | 避免自评偏见 |
| 消融开关 | 环境变量 + 代码参数 | 测试隔离 + 不污染生产路径 |
| 场景缓存 | JSONL 追加写 | 可复现、可审计、增量 |
| 随机种子 | 固定 seed | 结果可复现 |
| LLM 重试 | Judge 3 次取中位数 | 减少非确定性噪声 |
| Memory 消融 | 不独立做 | VehicleMemBench 已充分覆盖 |
