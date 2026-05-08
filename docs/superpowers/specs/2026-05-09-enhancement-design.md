# 知行车秘增强方案设计文档

日期：2026-05-09
目标：补六缺口 + 加四新能力，8周内完成，工程完整性优先

---

## 一、背景

开题报告规划四大层（情境建模、任务理解、策略决策、执行反馈），与中期报告对照后发现六缺口：

1. 反馈学习 no-op
2. 规则引擎仅 4 场景
3. 概率推断被移除
4. 隐私保护未实现
5. 多用户隔离未实现
6. 突发事件处理无独立模块（已由现有机制覆盖，仅需文档说明）

新增四能力：概率推断模块、隐私保护方案、多用户场景、实验数据可视化。缺口 3/4/5 同时属于新增能力。

## 二、缺口补漏

### 2.1 反馈学习恢复

**问题**：`MemoryBankStore.update_feedback()` 为 `pass`，`strategies.toml` 的 `reminder_weights` 不再更新。

**方案**：在 `store.py` 的 `update_feedback` 中恢复权重更新逻辑。

- accept → `reminder_weights[event_type] += 0.1`（上限 1.0）
- ignore → `reminder_weights[event_type] -= 0.1`（下限 0.1）
- 权重写回 `strategies.toml`
- Strategy Agent 读取权重时偏好高权重事件类型

**改动文件**：
- `app/memory/memory_bank/store.py`：`update_feedback` 实现
- `tests/stores/test_memory_bank_store.py`：补 accept/ignore 权重变化测试

**不影响**：
- workflow.py 的 `_strategies_store`（已在 `_strategy_node` 中读取并传入 prompt）
- MemoryBank 架构（权重存 strategies.toml 而非 FAISS metadata）

### 2.2 规则引擎补全

**问题**：`SAFETY_RULES` 仅 4 条，city_driving 和 traffic_jam 场景已定义但无专属规则。

**方案**：新增 2 条规则。

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| city_driving 限制 | `scenario == "city_driving"` | `allowed_channels: [audio]`, `max_frequency_minutes: 15` | 8 |
| traffic_jam 安抚 | `scenario == "traffic_jam"` | `allowed_channels: [audio, visual]`, `max_frequency_minutes: 10` | 7 |

**设计理由**：
- city_driving 比 highway 稍宽松（允许音频），频率限制更紧（15min vs 30min）
- traffic_jam 允许视觉通道（驾驶员在堵停时可看屏幕），频率较高（10min）
- 优先级低于 fatigue(20)/overloaded(15)，保证安全约束优先

**合并验证**：
- city_driving + fatigue → fatigue 优先，取 `only_urgent + audio`
- traffic_jam + overloaded → overloaded 优先，`postpone = true`

**改动文件**：
- `app/agents/rules.py`：`SAFETY_RULES` 追加
- `tests/test_rules.py`：补场景测试

### 2.3 突发事件处理（文档处置）

**问题**：开题规划"突发事件处理"，无独立模块。

**处置**：Strategy Agent 语义推理 + 规则引擎（postpone/only_urgent）联合覆盖。论文中说明此设计决策。更新 AGENTS.md 未解决问题列表。

---

## 三、新能力设计

### 3.1 概率推断模块

**背景**：开题规划"规则/阈值 + 概率推断 + 大模型生成"混合策略。实际仅有规则+LLM，概率推断层缺失。

**架构位置**：
```
DrivingContext → 规则引擎 → 概率推断 → LLM 策略决策 → postprocess_decision
                  (硬约束)    (软建议)    (语义推理)     (硬覆盖)
```

**推断两类**：

**A. 意图不确定性**：输入为当前查询中的关键词 + 历史记忆中的事件类型频率。输出置信度 (0~1) + 备选事件类型。

算法（朴素贝叶斯，无外部依赖）：
1. 从查询文本提取关键词（name entity，如时间词"明天上午"、地点词"会议室"、动作词"开会"）
2. P(event_type)：从记忆元数据统计各事件类型历史频率（type 字段计数归一化）。注意：此不同于 `reminder_weights`——后者是用户偏好反馈，前者是客观统计频率
3. P(keyword|event_type)：在历史记录中，该关键词出现时该事件类型的条件频率
4. 得分 = P(event_type) × ∏ P(kw_i|event_type)（朴素贝叶斯独立假设）
5. 对各候选类型得分归一化得置信度。最高分为主意图，次高为备选解释

空记忆时（冷启动）：所有类型等概率，依赖 LLM 语义推理兜底。

**B. 打断风险**：输入为 `DrivingContext` 现有字段，输出 0~1 风险分数。

公式：`0.4 × fatigue_level + 0.3 × workload_score + 0.2 × scenario_risk + 0.1 × speed_factor`

枚举到数值映射表：

| workload | workload_score | 说明 |
|----------|---------------|------|
| low | 0.1 | 低负荷，打断安全 |
| normal | 0.3 | 正常负荷 |
| high | 0.6 | 高负荷，谨慎打断 |
| overloaded | 0.9 | 过载——但 overloaded 已被规则引擎 postpone，概率推断不出现在此路径 |

| scenario | scenario_risk |
|----------|--------------|
| parked | 0.0 |
| city_driving | 0.4 |
| traffic_jam | 0.3 |
| highway | 0.7 |

| speed (km/h) | speed_factor |
|-------------|-------------|
| 0 | 0.0 |
| 1~40 | 0.3 |
| 41~80 | 0.5 |
| >80 | 0.8 |

（表值可在实现时根据实验调整，设计文档提供参考基线）

**输出注入方式**：结构化 JSON 注入 Strategy Agent prompt，不替代规则引擎输出。
```json
{"intent_confidence": 0.72, "alternative": "travel", "alt_confidence": 0.20, "interrupt_risk": 0.23}
```

**关键约束**：
- 不替代规则引擎硬约束。`postprocess_decision` 仍在最后执行
- 不修改工作流节点顺序
- 环境变量 `PROBABILISTIC_INFERENCE_ENABLED` 控制（默认开启，支持消融实验）
- 意图推断使用记忆元数据中事件 type 频率，不使用 `reminder_weights`——两者语义不同（统计 vs 偏好）

**实现文件**：
- 新 `app/agents/probabilistic.py`
- 改 `app/agents/workflow.py`：`_strategy_node` 调用推断
- 测试 `tests/test_probabilistic.py`

**无外部依赖**：纯 Python 计算。

### 3.2 隐私保护方案

**三层设计**：

**第一层：声明式隐私标记**

在写入记忆前自动脱敏位置信息：
- 经纬度截断至小数点后 2 位（约 1km 精度）
- 地址只保留街道级
- 新 `app/memory/privacy.py` 提供脱敏工具

**第二层：数据可携带性**

新增 GraphQL mutation：
```graphql
mutation {
  exportData: JSON        # 所有存储数据快照
  deleteAllData: Boolean  # 一键清除含 FAISS 索引
}
```

`exportData` 导出文件清单：`events.toml`, `contexts.toml`, `preferences.toml`, `feedback.toml`, `strategies.toml`, `scenario_presets.toml`, `experiment_results.toml`, `memorybank/index.faiss`, `memorybank/metadata.json`, `memorybank/extra_metadata.json`。

**第三层：本地优先声明**

在 AGENTS.md 和 README 中明确声明：
- 所有数据本地存储
- 无云端同步、无遥测、无第三方共享
- LLM 调用仅发送当前查询文本

**不做**：加密存储、差分隐私、GDPR 全栈合规（原型系统）。

**改动文件**：
- 新 `app/memory/privacy.py`
- 改 `app/api/graphql_schema.py`：加 `exportData`/`deleteAllData` 类型
- 改 `app/api/resolvers/mutation.py`：加 resolver
- 文档 AGENTS.md/README.md

### 3.3 多用户场景

**背景**：MemoryBank 底层已支持 speaker 存储和说话人感知检索。上层（API、策略、偏好）为单用户设计。

**扩展三层**：

**API 层**：`ProcessQueryInput` 新增 `currentUser: str`。

**偏好层**：`strategies.toml` 分用户权重。
```toml
[reminder_weights.张三]
meeting = 0.8
travel = 0.5
```
无分用户权重时回退到全局权重。

**规则层**：新增乘客在场规则。条件中的"多 speaker"判定基于 `DrivingContext.passengers: list[str]` 非空。

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| 乘客在场放宽 | 场景 != highway 且多 speaker | `allowed_channels` 追加 `visual` | 3 |

**不改**：检索管道（speaker 字段已就绪）、摘要/人格（已按用户分组分析）、FAISS 结构。

**改动文件**：
- 改 `app/api/graphql_schema.py`：`ProcessQueryInput` 加 `currentUser`
- 改 `app/api/resolvers/mutation.py`：传 `currentUser`
- 改 `app/agents/workflow.py`：`_strategy_node` 读取分用户权重
- 改 `app/agents/rules.py`：加乘客规则
- 改 `app/schemas/context.py`：`DrivingContext` 加 `passengers: list[str] = []`
- 测试 `tests/test_multi_user.py`

### 3.4 实验数据可视化

**数据格式**：`data/experiment_results.toml`，用户从 VehicleMemBench 手动填入。
```toml
[strategies.memory_bank]
exact_match = 0.52
field_f1 = 0.71
value_f1 = 0.67
```

**GraphQL 查询**：`experimentResults` 返回五策略对比数据。

**WebUI 可视化**：
- 新增「实验结果」标签页
- Chart.js（CDN，无构建步骤）
- 五策略并排柱状图（Exact Match / Field F1 / Value F1）
- 高亮本系统（MemoryBank）

**改动文件**：
- 新 `app/storage/experiment_store.py`
- 改 `app/api/graphql_schema.py`：`ExperimentResults` 类型
- 改 `app/api/resolvers/query.py`：`experimentResults` query
- 改 `webui/index.html` + `webui/app.js`：图表面板
- 测试 `tests/test_experiment_results.py`

---

## 四、文件变更汇总

| 文件 | 变更类型 | 关联需求 |
|------|---------|---------|
| `app/agents/rules.py` | 修改 | 2.2 规则补全, 3.3 多用户 |
| `app/agents/workflow.py` | 修改 | 3.1 概率推断, 3.3 多用户 |
| `app/agents/probabilistic.py` | **新增** | 3.1 概率推断 |
| `app/memory/memory_bank/store.py` | 修改 | 2.1 反馈学习 |
| `app/memory/privacy.py` | **新增** | 3.2 隐私保护 |
| `app/schemas/context.py` | 修改 | 3.3 多用户 |
| `app/storage/experiment_store.py` | **新增** | 3.4 实验可视化 |
| `app/api/graphql_schema.py` | 修改 | 3.2 隐私, 3.3 多用户, 3.4 可视化 |
| `app/api/resolvers/query.py` | 修改 | 3.4 实验可视化 |
| `app/api/resolvers/mutation.py` | 修改 | 3.2 隐私, 3.3 多用户 |
| `webui/index.html` | 修改 | 3.4 实验可视化 |
| `webui/app.js` | 修改 | 3.4 实验可视化 |
| `AGENTS.md` | 修改 | 2.3 文档处置, 3.2 隐私声明 |
| `README.md` | 修改 | 3.2 隐私声明 |
| `tests/stores/test_memory_bank_store.py` | 修改 | 2.1 反馈学习 |
| `tests/test_rules.py` | 修改 | 2.2 规则补全 |
| `tests/test_probabilistic.py` | **新增** | 3.1 概率推断 |
| `tests/test_multi_user.py` | **新增** | 3.3 多用户 |
| `tests/test_experiment_results.py` | **新增** | 3.4 实验可视化 |

**统计**：新增 5 文件，修改 13 文件。

---

## 五、约束与假设

1. 时间约束：8 周，第 7-8 周为论文撰写缓冲
2. 技术约束：不加新依赖库（概率推断纯 Python，Chart.js CDN 不算依赖）
3. 架构约束：不改工作流节点顺序，不改 FAISS 索引结构
4. 测试约束：所有新功能必须覆盖测试
5. 向后兼容：不传 `currentUser` 时行为等同于旧版单用户模式
