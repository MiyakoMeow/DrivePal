# 知行车秘 - 车载AI智能体原型系统

基于大语言模型的车载智能提醒与日程管理智能体，支持多种记忆检索策略的自动化对比实验（LLM-as-Judge 评估）。

---

## 目录

- [项目概述](#项目概述)
- [项目结构](#项目结构)
- [核心功能](#核心功能)
  - [多Agent工作流](#1-多agent工作流)
  - [记忆检索系统](#2-记忆检索系统)
  - [实验对比框架](#3-实验对比框架)
  - [REST API](#4-rest-api)
  - [Web界面](#5-web界面)
- [快速开始](#快速开始)
- [实验流程](#实验流程)
- [配置说明](#配置说明)
- [测试](#测试)
- [技术栈](#技术栈)

---

## 项目概述

知行车秘是一个车载AI智能体原型系统，专注于**驾驶场景下的智能提醒和日程管理**。系统基于 LangGraph 构建多Agent协作工作流，支持四种记忆检索策略的对比实验。

### 设计目标

1. **驾驶安全优先**：根据驾驶员状态（专注驾驶、交通拥堵、高速行驶等）智能调整提醒方式
2. **多策略对比**：支持关键词、纯LLM、向量嵌入、MemoryBank 四种记忆检索方式的性能对比
3. **可解释决策**：明确输出提醒决策的理由，支持用户反馈迭代优化

---

## 项目结构

```
thesis-cockpit-memo/
├── app/                          # 应用核心代码
│   ├── agents/                   # AI智能体核心模块
│   │   ├── workflow.py           # LangGraph工作流编排
│   │   ├── state.py              # Agent状态类型定义
│   │   └── prompts.py            # 系统提示词模板
│   ├── models/                   # AI模型封装
│   │   ├── chat.py               # LLM调用封装
│   │   ├── embedding.py          # 嵌入模型封装
│   │   └── settings.py           # 多provider配置 + Judge配置
│   ├── memory/                   # 记忆模块
│   │   ├── memory.py             # MemoryModule调度层
│   │   ├── types.py              # MemoryMode枚举
│   │   ├── schemas.py            # 数据模型定义
│   │   └── stores/               # 各记忆后端实现
│   │       ├── base.py           # BaseMemoryStore + keyword检索
│   │       ├── embedding_store.py # Embedding检索（混合检索）
│   │       ├── llm_store.py      # LLM语义检索
│   │       └── memory_bank_store.py # MemoryBank后端
│   ├── experiment/               # 实验对比模块
│   │   ├── runners/              # 三阶段Pipeline运行器
│   │   │   ├── prepare.py        # Prepare阶段：数据加载+预热
│   │   │   ├── execute.py        # Run阶段：执行测试+规则评估
│   │   │   ├── judge.py          # Judge阶段：LLM-as-Judge评分
│   │   │   └── evaluate.py       # 规则评估函数
│   │   └── loaders/              # 数据集加载器
│   │       ├── sgd_calendar.py   # SGD-Calendar数据集
│   │       └── scheduler.py      # Scheduler数据集
│   ├── storage/                  # 存储模块
│   │   └── json_store.py         # JSON文件存储
│   └── api/                      # FastAPI接口
│       └── main.py               # REST API
├── config/                       # 配置文件
│   ├── scenarios.json            # 驾驶场景模板
│   ├── driver_states.json        # 驾驶员状态配置
│   └── evaluation_config.json    # 评估配置
├── data/                         # 数据目录（运行时生成）
├── tests/                        # 测试
├── webui/                        # Web界面
├── run_experiment.py             # 实验Pipeline CLI
├── main.py                       # Web服务入口
└── pyproject.toml                # 项目配置
```

---

## 核心功能

### 1. 多Agent工作流

基于 LangGraph 构建的四阶段工作流，每个阶段由专门的Agent处理：

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌─────────────────┐
│   用户输入    │ ──▶ │ Context Agent│ ──▶ │  Task Agent    │ ──▶ │ Strategy Agent  │
└─────────────┘     └──────────────┘     └────────────────┘     └─────────────────┘
                                                                           │
                                                                           ▼
                                                                     ┌─────────────────┐
                                                                     │ Execution Agent  │
                                                                     └─────────────────┘
```

#### Agent职责

| Agent | 输入 | 输出 | 说明 |
|-------|------|------|------|
| **Context Agent** | 用户输入 + 历史记忆 | JSON上下文对象 | 整合时间、位置、交通、用户偏好 |
| **Task Agent** | 用户输入 + 上下文 | JSON任务对象 | 事件抽取、类型归因（meeting/travel/shopping/contact） |
| **Strategy Agent** | 上下文 + 任务 + 个性化策略 | JSON决策对象 | 决定提醒时机、方式、内容 |
| **Execution Agent** | 决策对象 | 执行结果 + event_id | 存储事件，返回提醒内容 |

---

### 2. 记忆检索系统

支持四种检索模式，可通过 `memory_mode` 参数切换：

#### 检索模式对比

| 模式 | 实现类 | 原理 | 适用场景 |
|------|--------|------|----------|
| `keyword` | `_search_by_keyword` | 关键词大小写不敏感匹配 | 快速、简单查询 |
| `llm_only` | `_search_by_llm` | LLM判断语义相关性 | 复杂语义理解 |
| `embeddings` | `_search_by_embeddings` | BGE向量余弦相似度 > 0.7 | 语义模糊查询 |
| `memorybank` | `MemoryBankBackend` | Ebbinghaus遗忘曲线 + 分层记忆 | 长期记忆管理 |

#### MemoryBank 分层记忆结构

基于 MemoryBank 论文实现的三层记忆架构：

```
Interaction (原始交互)
  ├── id, query, response, memory_strength
        │
        ▼ 聚合
Event (语义摘要)
  ├── content, interaction_ids, memory_strength, date_group
        │
        ▼ 聚合
Summary (层级摘要)
  ├── daily_summaries: {date → {content, memory_strength}}
  └── overall_summary: str
```

**核心机制：**

- **遗忘曲线**：`retention = e^(-days / (5 × strength))`，模拟人类记忆衰减
- **回忆强化**：检索命中时 `memory_strength += 1`，增加记忆留存
- **自动聚合**：语义相似的交互自动聚合为同一事件（余弦相似度 ≥ 0.8 或关键词重叠 ≥ 50%）
- **层级摘要**：事件数达到日阈值后生成 daily_summary，daily_summary 数量达到总阈值后生成 overall_summary
- **结果展开**：检索命中事件时，自动附加其关联的原始交互记录

#### 反馈学习机制

用户反馈（accept/ignore）会更新 `strategies.json` 中的 `reminder_weights`：

- **accept**：对应事件类型权重 +0.1（上限1.0）
- **ignore**：对应事件类型权重 -0.1（下限0.1）

---

### 3. 实验对比框架

三阶段 Pipeline 架构：Prepare → Execute → Judge，每阶段可独立运行/重试。

#### Pipeline 流程

```
[数据集] → Prepare → data/exp/{run_id}/prepared.json
                         ↓
                       Execute → data/exp/{run_id}/results/{method}_raw.json
                         ↓
                       Judge → data/exp/{run_id}/judged/final_report.json
```

#### 四种记忆后端

| 后端 | 实现类 | 原理 | 适用场景 |
|------|--------|------|----------|
| `keyword` | `BaseMemoryStore` | 关键词大小写不敏感匹配 + 子串搜索 | 快速、简单查询 |
| `llm_only` | `LLMOnlyMemoryStore` | LLM判断语义相关性 | 复杂语义理解 |
| `embeddings` | `EmbeddingMemoryStore` | BGE向量余弦相似度 + keyword fallback | 语义模糊查询 |
| `memorybank` | `MemoryBankBackend` | Ebbinghaus遗忘曲线 + 分层记忆 + 混合检索 | 长期记忆管理 |

#### 运行实验

```bash
# 全流程（推荐）
uv run python run_experiment.py all --datasets sgd_calendar scheduler --test-count 50

# 分阶段运行
uv run python run_experiment.py prepare --datasets sgd_calendar scheduler --test-count 50 --seed 42
uv run python run_experiment.py run --run-id <run_id>
uv run python run_experiment.py judge --run-id <run_id>
```

#### CLI 参数

| 子命令 | 参数 | 默认值 | 说明 |
|--------|------|--------|------|
| `prepare` | `--datasets` | `sgd_calendar scheduler` | 使用的数据集 |
| `prepare` | `--test-count` | `50` | 每数据集测试用例数 |
| `prepare` | `--warmup-ratio` | `0.7` | 预热数据占比 |
| `prepare` | `--seed` | `42` | 随机种子 |
| `run` | `--run-id` | 必填 | Prepare 生成的 run ID |
| `judge` | `--run-id` | 必填 | 同上 |

#### LLM-as-Judge 评估

使用独立 Judge 模型对每个后端的输出做多维评分（1-5分）：

| 维度 | 权重 | 说明 |
|------|------|------|
| `memory_recall` | 25% | 是否正确利用了历史记忆/上下文信息 |
| `relevance` | 25% | 回复是否与用户意图相关 |
| `task_quality` | 20% | 日程管理任务是否被正确处理 |
| `coherence` | 15% | 驾驶场景下是否合理连贯 |
| `helpfulness` | 15% | 对驾驶员的实际帮助程度 |

Judge 配置在 `config/llm.json` 的 `judge` 字段，支持环境变量覆盖：`JUDGE_MODEL` / `JUDGE_BASE_URL` / `JUDGE_API_KEY`。

#### 实验数据结构

```
data/exp/{run_id}/
├── prepared.json              # 划分方案 + 测试用例 + 预热数据引用
├── warmup/                    # 预热数据
│   ├── sgd_calendar.json
│   └── scheduler.json
├── stores/                    # 各后端预热的记忆库
│   ├── keyword/
│   ├── llm_only/
│   ├── embeddings/
│   └── memorybank/
├── results/                   # Execute 阶段原始结果
│   ├── keyword_raw.json
│   ├── llm_only_raw.json
│   ├── embeddings_raw.json
│   └── memorybank_raw.json
└── judged/                    # Judge 阶段评分
    ├── keyword_judged.json
    ├── llm_only_judged.json
    ├── embeddings_judged.json
    ├── memorybank_judged.json
    └── final_report.json      # 汇总报告
```

#### 数据集

| 数据集 | 来源 | 样本量 | 说明 |
|--------|------|--------|------|
| **SGD-Calendar** | `vidhikatkoria/SGD_Calendar` (HuggingFace) | 60 条 | 日程管理对话 |
| **Scheduler** | `shawnha/scheduler_dataset` (HuggingFace) | 1110 条 | 航班/酒店/日程查询 |

#### 断点续评

Judge 阶段支持断点续评：已成功评判的用例会被跳过，只重试失败的。重新运行 `judge` 即可继续。

---

### 4. REST API

#### 基础信息

- 基础路径：`/api`
- 服务启动：`python main.py`（默认 `0.0.0.0:8000`）
- Web界面：`/` 根路径返回 `webui/index.html`

#### API端点

##### POST `/api/query` - 处理用户查询

**请求体：**

```json
{
  "query": "明天上午9点有个会议",
  "memory_mode": "keyword"   // 可选: keyword | llm_only | embeddings | memorybank
}
```

**响应：**

```json
{
  "result": "提醒已发送: 明天上午9点会议提醒",
  "event_id": "20260327120000_a1b2c3d4"
}
```

##### POST `/api/feedback` - 提交反馈

**请求体：**

```json
{
  "event_id": "20260327120000_a1b2c3d4",
  "action": "accept",        // accept | ignore
  "modified_content": "修改后的内容"  // 可选
}
```

**响应：**

```json
{
  "status": "success"
}
```

##### GET `/api/history` - 获取历史记录

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 10 | 返回记录数（0 = 全部） |

##### GET `/api/experiment/report` - 获取实验报告

---

### 5. Web界面

基于纯HTML/CSS/JavaScript的单页应用，提供：

- **设置面板**：选择记忆检索模式
- **输入面板**：文本输入框发送查询
- **响应面板**：显示AI回复，支持接受/忽略反馈
- **历史记录面板**：展示最近10条交互记录

---

## 快速开始

### 环境要求

- Python 3.13+
- 本地部署 vLLM（Qwen3.5-2B）或 OpenAI 兼容 API

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
# 设置 vLLM 服务地址（默认 http://localhost:8000/v1）
export VLLM_BASE_URL="http://localhost:8000/v1"

# 如需使用 DeepSeek 作为备用
# export DEEPSEEK_API_KEY="your-api-key"
```

### 3. 初始化数据目录

```bash
python -c "from app.storage.init_data import init_storage; init_storage()"
```

### 4. 启动Web服务

```bash
python main.py
```

访问 http://localhost:8000

### 5. 运行对比实验

```bash
# 全流程（推荐）
uv run python run_experiment.py all --datasets sgd_calendar scheduler --test-count 50

# 分阶段运行
uv run python run_experiment.py prepare --datasets sgd_calendar --test-count 30 --seed 42
uv run python run_experiment.py run --run-id <run_id>
uv run python run_experiment.py judge --run-id <run_id>
```

---

## 配置说明

### 模型配置 (`config/llm.json`)

所有 LLM、Embedding、Judge 模型配置统一在 `config/llm.json` 管理，Python 侧由 `app/models/settings.py` 加载（`LLMSettings.load()`）。

```json
{
  "llm": [
    {
      "model": "qwen3.5-2b",
      "base_url": "http://localhost:50721/v1",
      "api_key": "local",
      "temperature": 0.7
    }
  ],
  "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
  "judge": {
    "model": "qwen3.5-2b",
    "base_url": "http://localhost:50721/v1",
    "api_key": "local",
    "temperature": 0.1
  }
}
```

**环境变量覆盖：**

| 变量 | 说明 |
|------|------|
| `VLLM_BASE_URL` | 默认 LLM provider 的 base_url |
| `JUDGE_MODEL` | Judge 模型名称（优先于 llm.json 中的 judge 字段） |
| `JUDGE_BASE_URL` | Judge 模型的 base_url |
| `JUDGE_API_KEY` | Judge 模型的 API key |
| `OPENAI_MODEL` / `DEEPSEEK_MODEL` | 自动注册为额外 LLM provider |

### 驾驶场景配置 (`config/scenarios.json`)

| 类型 | 说明 | 示例模板 |
|------|------|----------|
| `schedule_check` | 日程查询 | "今天有什么安排？" |
| `event_add` | 添加事件 | "提醒我下午三点开会" |
| `event_delete` | 删除事件 | "取消明天的会议" |
| `general` | 通用对话 | "你好" |

### 驾驶员状态配置 (`config/driver_states.json`)

| 状态 | 说明 | 容忍度 | 合适方式 |
|------|------|--------|----------|
| `focused` | 专注驾驶 | 低 | visual, audio |
| `traffic_jam` | 交通拥堵 | 中 | visual, audio |
| `parked` | 停车状态 | 高 | visual, audio, detailed |
| `highway` | 高速行驶 | 极低 | audio |
| `city_driving` | 城市驾驶 | 低 | visual, audio |

---

## 数据存储

### 存储目录结构

```
data/
├── events.json               # 事件历史（含 interaction_ids）
├── interactions.json          # 原始交互记录（MemoryBank）
├── memorybank_summaries.json  # MemoryBank 层级摘要
│   ├── daily_summaries: {}    # {date → {content, memory_strength, event_count}}
│   └── overall_summary: ""    # 总摘要
├── contexts.json            # 上下文缓存
├── preferences.json         # 用户偏好
├── feedback.json            # 用户反馈记录
├── strategies.json          # 个性化策略
└── experiment_results.json   # 实验结果
```

### 存储接口 (`app/storage/json_store.py`)

```python
store = JSONStore(data_dir, "filename.json", default_factory=list)

store.read()           # 读取数据
store.write(data)      # 写入数据
store.append(item)     # 追加单项（仅list类型）
store.update(key, val) # 更新键值（仅dict类型）
```

---

## 测试

### 运行所有测试

```bash
uv run pytest tests/ -v
```

### 测试覆盖模块

| 文件 | 说明 |
|------|------|
| `test_prepare.py` | Prepare 阶段：数据划分、预热、seed 可复现 |
| `test_execute.py` | Execute 阶段：多后端执行、raw 输出保留 |
| `test_judge.py` | Judge 阶段：LLM-as-Judge 评分、断点续评 |
| `test_evaluate.py` | 规则评估函数 |
| `test_e2e_pipeline.py` | 端到端 Pipeline 集成测试 |
| `test_experiment_runner.py` | Workflow 集成：数据隔离、评估指标 |
| `stores/test_keyword_store.py` | Keyword 记忆后端 |
| `stores/test_embedding_store.py` | Embedding 记忆后端 |
| `stores/test_llm_store.py` | LLM 记忆后端 |
| `stores/test_memory_bank_store.py` | MemoryBank 后端 |
| `test_api.py` | API 端点集成测试 |
| `test_chat.py` | Chat 驱动 LLM 记忆搜索、Workflow 上下文注入 |
| `test_embedding.py` | Embedding 语义检索与聚合 |
| `test_memory_bank.py` | 遗忘曲线、层级摘要、交互聚合 |
| `test_storage.py` | 跨实例持久化、反馈策略更新 |
| `test_settings.py` | 模型配置加载与环境变量覆盖 |
| `test_schemas.py` | 数据模型定义 |
| `test_memory_types.py` | MemoryMode 枚举 |
| `test_memory_module_facade.py` | MemoryModule 调度层 |
| `test_memory_store_contract.py` | 记忆后端契约测试 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web框架** | FastAPI + Uvicorn |
| **AI工作流** | LangChain + LangGraph |
| **LLM支持** | Qwen3.5-2B (vLLM, 默认), DeepSeek-chat, GPT-4, Claude-3 (OpenAI兼容接口) |
| **LLM推理** | vLLM (本地部署), OpenAI兼容接口 |
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线 + 分层摘要) |
| **数据存储** | JSON文件 (标准库json) |
| **数据集** | HuggingFace Datasets |
| **开发工具** | uv (包管理), pytest (测试), ruff (lint), ty (类型检查) |

---

## License

MIT
