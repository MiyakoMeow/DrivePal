# Markdown 报告结构重设计

## 1. 背景

当前 `markdown_formatters.py` 生成的报告结构存在数据重复和逻辑混杂的问题：
- report.json 中的数值分散在"总览"和"详细分析"中重复出现
- 固定内容（实验组介绍、指标含义）与实验结果混杂
- 缺乏清晰的结果分析章节

## 2. 目标

重新设计报告结构，遵循以下原则：
1. **数据唯一性**：report.json 中的各指标值只出现一次
2. **结构清晰**：按"头内容 → 固定内容 → 实验结果 → 结果分析"顺序组织
3. **便于横向对比**：实验结果以表格形式呈现

## 3. 报告结构

### 3.1 头内容

```markdown
# VehicleMemBench 基准测试报告

- 生成时间：{timestamp}
- 评估模型：{model_name}
- 记忆类型：{type_names}
```

### 3.2 固定内容

#### 3.2.1 实验组介绍

| 实验组 | 记忆类型 | 描述 | 理论意义 |
|--------|----------|------|----------|
| none | Raw History | 无历史信息 | 基线性能 |
| gold | Gold Memory | 提供真实记忆 | 理论上限 |
| key_value | Key-Value Store | 结构化键值存储 | 精确检索 |
| memory_bank | MemoryBank | 遗忘曲线记忆 | 遗忘曲线检索 |

#### 3.2.2 指标含义

| 指标 | 描述 |
|------|------|
| ESM (Exact Match Rate) | 最终状态完全匹配率 |
| F1 Positive | 字段级 F1（是否修改了正确字段） |
| F1 Change | 值级 F1（修改后的值是否正确） |
| F1 Negative | 负类 F1（是否避免错误修改） |
| Memory Score | 相对于 GOLD 的 ESM 比值 |
| Δ% (vs Gold) | 与 GOLD 的 ESM 差距百分比 |
| Avg Calls | 平均工具调用数 |
| Avg Tokens | 平均输出 token 数 |

### 3.3 实验结果

#### 3.3.1 核心指标总表（横向对比）

```markdown
## 3. 实验结果

| 记忆类型 | ESM | F1 Positive | F1 Change | Memory Score | Δ% (vs Gold) | Avg Calls | Avg Tokens | 失败数 |
|----------|-----|-------------|-----------|--------------|---------------|-----------|------------|--------|
| none     | ... | ...         | ...       | ...          | ...           | ...       | ...        | ...    |
| gold     | ... | ...         | ...       | -            | -             | ...       | ...        | ...    |
| key_value| ... | ...         | ...       | ...          | ...           | ...       | ...        | ...    |
| memory_bank | ... | ...         | ...       | ...          | ...           | ...       | ...        | ...    |
```

#### 3.3.2 详细指标（按记忆类型）

可选折叠的详细表格，包含所有细粒度指标：
- Exact Match Rate
- F1 Positive / F1 Negative / F1 Change
- Change Accuracy
- Avg Pred Calls
- Avg Output Token
- 失败查询数
- Memory Score（如有）

#### 3.3.3 按推理类型细分

表格形式展示不同推理类型下的 ESM 表现。

### 3.4 结果分析

#### 3.4.1 各记忆类型表现分析
- 各类型 ESM 对比
- 与 GOLD 理论上限的差距
- Memory Score 分析

#### 3.4.2 按推理类型交叉对比
- 各推理类型下表现最佳的记忉系统

#### 3.4.3 问题案例分析
- 完全匹配案例
- 过度修改案例（FP 最高）
- 遗漏调用案例（FN 最高）

#### 3.4.4 总结
- 本次评估概况
- 主要发现

## 4. 实现要点

### 4.1 数据流

```
report.json → 实验结果（唯一出现位置）
           → 结果分析（引用但不重复数值）
```

### 4.2 函数设计

- `md_header()`: 生成头内容
- `md_experiment_groups()`: 生成实验组介绍
- `md_metric_definitions()`: 生成指标定义
- `md_results_table()`: 生成实验结果总表
- `md_results_detail()`: 生成详细指标（可选折叠）
- `md_reasoning_breakdown()`: 生成按推理类型细分
- `md_analysis()`: 生成结果分析（综合 md_reasoning_cross_comparison、md_query_analysis、md_summary）

### 4.3 注意事项

- 实验结果中的数值**必须且只能出现一次**
- 结果分析部分只做文字性描述和分析，不重复具体数值
- 保持与现有 JSON 数据结构兼容

## 5. 变更范围

仅修改 `benchmark/VehicleMemBench/markdown_formatters.py`，不修改：
- `reporter.py`
- 数据生成逻辑
- 评估指标计算
