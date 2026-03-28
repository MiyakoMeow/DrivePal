# 对比实验重新设计：四后端 LLM-as-Judge 评估

## 背景

现有实验框架使用基于规则的评估（意图匹配、否定处理、关键词重叠），无法准确衡量记忆后端的语义质量。需要重新设计为三阶段 Pipeline 架构，引入 LLM-as-Judge 多维评分。

## 需求

- 对比 4 个记忆后端：keyword / llm_only / embeddings / memorybank
- 使用 2 个外部数据集：SGD-Calendar + Scheduler
- LLM-as-Judge 多维评分（独立 judge 模型）
- 保留现有规则评估指标
- 使用外部 OpenAI 兼容 API + 本地 embeddings
- 结果输出为 JSON

## 架构：Pipeline 分离式

三个独立阶段，每阶段可单独运行/重试。

```
[数据集] → Prepare → data/exp/{run_id}/prepared.json
                         ↓
                       Run → data/exp/{run_id}/results/{method}_raw.json
                         ↓
                      Judge → data/exp/{run_id}/judged/final_report.json
```

## 目录结构变更

```
app/experiment/
├── runners/                    # 新目录
│   ├── prepare.py             # Prepare 阶段
│   ├── execute.py             # Run 阶段
│   └── judge.py               # Judge 阶段
├── loaders/                    # 保持不变
│   ├── sgd_calendar.py
│   └── scheduler.py
├── evaluator/                  # 保持不变
└── runner.py                   # 删除
```

## 阶段 1：Prepare

### 职责

1. 加载指定数据集（SGD-Calendar / Scheduler）
2. 按 seed 随机 shuffle，按 warmup_ratio 划分预热/测试集
3. 对每个后端，将预热数据写入独立记忆库
4. 持久化划分方案

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--datasets` | `sgd_calendar scheduler` | 使用的数据集 |
| `--test-count` | 50 | 每数据集测试用例数 |
| `--warmup-ratio` | 0.7 | 预热数据占比 |
| `--seed` | 42 | 随机种子 |

### 数据目录

```
data/exp/{run_id}/
├── prepared.json              # 划分方案 + 测试用例 + 预热数据引用
├── warmup/                    # 预热数据（独立文件，避免 prepared.json 过大）
│   ├── sgd_calendar.json
│   └── scheduler.json
├── stores/                    # 各后端预热的记忆库
│   ├── keyword/
│   ├── llm_only/
│   ├── embeddings/
│   └── memorybank/
```

### 预热写入

对每个后端：
1. 创建 `MemoryModule` 实例，指向 `stores/{method}/`
2. 逐条调用 `memory_module.write_interaction(input, response)` 写入预热数据
3. response 使用 LLM 生成：将 input 送入工作流 LLM，获取简短日程回复作为 response
   - 这样 embeddings/memorybank 后端能建立有意义的语义索引
   - Prepare 阶段需要调用 LLM API（不可离线重跑），但只需处理预热数据量（~70 条）

### prepared.json 格式

```json
{
  "run_id": "20260329_142000",
  "seed": 42,
  "warmup_ratio": 0.7,
  "datasets": {
    "sgd_calendar": {"warmup_count": 42, "test_count": 18},
    "scheduler": {"warmup_count": 35, "test_count": 15}
  },
  "test_cases": [
    {"id": "sgd_0", "input": "...", "type": "event_add", "dataset": "sgd_calendar"}
  ],
  "warmup_files": {
    "sgd_calendar": "warmup/sgd_calendar.json",
    "scheduler": "warmup/scheduler.json"
  }
}
```

`warmup/*.json` 格式：
```json
[
  {"id": "sgd_5", "input": "...", "type": "event_add", "response": "LLM生成的回复"}
]
```

## 阶段 2：Run（Execute）

### 职责

1. 读取 prepared.json 中的测试用例
2. 对每个后端（使用预热的记忆库），执行所有测试用例
3. 收集原始输出 + 现有规则评估指标

### 执行流程

```
for method in [keyword, llm_only, embeddings, memorybank]:
    workflow = create_workflow(data_dir=stores/{method}/, memory_mode=method)
    for case in test_cases:
        result, event_id = workflow.run(case["input"])
        raw_output = extract_output(result, data_dir)
        metrics = { latency_ms, task_completed, semantic_accuracy, context_relatedness }
        save_raw(method, case, result, raw_output, metrics)
```

- 测试用例按顺序执行，不做用例间清理（保持记忆累积）
- 每个后端使用独立的 stores/{method}/ 目录

### 输出

```json
// results/{method}_raw.json
{
  "run_id": "...",
  "method": "keyword",
  "cases": [
    {
      "id": "sgd_0",
      "input": "I need to schedule a meeting",
      "type": "event_add",
      "output": "提醒已发送: ...",
      "raw_output": "提取的决策内容",
      "event_id": "...",
      "latency_ms": 1234.5,
      "task_completed": true,
      "semantic_accuracy": 0.8,
      "context_relatedness": 0.6,
      "error": null
    }
  ]
}
```

## 阶段 3：Judge

### 职责

1. 读取所有后端的 raw results
2. 对每条用例，将 input + output 送入独立 judge 模型
3. 多维评分（1-5 分）+ 加权总分
4. 汇总生成 final_report.json

### 评估维度

| 维度 | 说明 | 权重 |
|------|------|------|
| memory_recall | 输出是否正确利用了历史记忆/上下文 | 0.25 |
| relevance | 回复是否与用户意图相关 | 0.25 |
| task_quality | 日程管理任务是否正确处理 | 0.20 |
| coherence | 驾驶场景下是否合理连贯 | 0.15 |
| helpfulness | 对驾驶员的实际帮助程度 | 0.15 |

### Judge Prompt

```
你是一个车载AI智能体的质量评估专家。请评估以下系统回复的质量。

## 用户输入
{input}

## 系统回复
{output}

## 任务类型
{task_type}

## 评估维度
请对以下每个维度打分（1-5分），并简要说明理由：

1. **记忆召回 (memory_recall)**: 系统是否正确利用了历史记忆/上下文信息？(1=完全未利用, 5=完美利用)
2. **响应相关性 (relevance)**: 回复是否与用户意图紧密相关？(1=完全无关, 5=高度相关)
3. **任务完成质量 (task_quality)**: 日程管理任务是否被正确处理？(1=完全错误, 5=完美完成)
4. **上下文一致性 (coherence)**: 回复在驾驶场景下是否合理连贯？(1=完全不连贯, 5=非常连贯)
5. **整体有用性 (helpfulness)**: 对驾驶员的实际帮助程度？(1=无帮助, 5=非常有帮助)

请以JSON格式输出评分结果：
{
  "memory_recall": {"score": N, "reason": "..."},
  "relevance": {"score": N, "reason": "..."},
  "task_quality": {"score": N, "reason": "..."},
  "coherence": {"score": N, "reason": "..."},
  "helpfulness": {"score": N, "reason": "..."}
}
```

### Judge 配置

在 `config/llm.json` 新增 `judge` 字段：

```json
{
  "llm": [...],
  "embedding": [...],
  "judge": {
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "...",
    "temperature": 0.1
  }
}
```

环境变量覆盖：`JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY`

### 输出

```json
// judged/{method}_judged.json
{
  "run_id": "...",
  "method": "keyword",
  "judge_model": "deepseek-chat",
  "cases": [
    {
      "id": "sgd_0",
      "scores": {
        "memory_recall": {"score": 4, "reason": "..."},
        "relevance": {"score": 5, "reason": "..."},
        "task_quality": {"score": 3, "reason": "..."},
        "coherence": {"score": 4, "reason": "..."},
        "helpfulness": {"score": 4, "reason": "..."}
      },
      "weighted_total": 4.05
    }
  ]
}
```

```json
// judged/final_report.json
{
  "run_id": "...",
  "judge_model": "deepseek-chat",
  "summary": {
    "keyword": {
      "avg_weighted_total": 3.85,
      "avg_memory_recall": 3.2,
      "avg_relevance": 4.1,
      "avg_task_quality": 3.8,
      "avg_coherence": 4.0,
      "avg_helpfulness": 3.9,
      "avg_latency_ms": 1200,
      "task_completion_rate": 0.95,
      "case_count": 33
    },
    "llm_only": { "..." : "..." },
    "embeddings": { "..." : "..." },
    "memorybank": { "..." : "..." }
  }
}
```

## CLI

```bash
# 全流程
uv run python run_experiment.py all --judge-model deepseek-chat

# 分阶段
uv run python run_experiment.py prepare --datasets sgd_calendar scheduler --test-count 50
uv run python run_experiment.py run --run-id <id>
uv run python run_experiment.py judge --run-id <id> --judge-model deepseek-chat
```

## 错误处理

- Judge API 失败：单条标记 `judge_error`，不中断整体，支持断点续评
- Run 阶段失败：单条标记 `error`，不中断，judge 评分记为全 0
- Judge 重试：跳过已成功评判的用例，只重试失败的，最多 3 次

## 并发

- Run 阶段：串行（记忆状态依赖 + API 限流）
- Judge 阶段：可选并发（`--concurrency N`，默认 1）

## 变更清单

| 变更 | 文件 |
|------|------|
| 新增 | `app/experiment/runners/__init__.py` |
| 新增 | `app/experiment/runners/prepare.py` |
| 新增 | `app/experiment/runners/execute.py` |
| 新增 | `app/experiment/runners/judge.py` |
| 修改 | `app/models/settings.py` — 新增 JudgeProviderConfig |
| 修改 | `config/llm.json` — 新增 judge 配置节 |
| 重写 | `run_experiment.py` — 子命令式 CLI |
| 删除 | `app/experiment/runner.py` — 旧 ExperimentRunner |
| 保留 | 数据集加载器、MemoryModule、各 store、规则评估函数（`runner.py` 中） |
