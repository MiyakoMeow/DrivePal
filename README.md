# 知行车秘 - 车载AI智能体原型系统

基于大语言模型的车载智能提醒与日程管理智能体，支持多种记忆检索策略对比实验。

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
- [API文档](#api文档)
- [配置说明](#配置说明)
- [数据存储](#数据存储)
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
│   ├── __init__.py              # 存储初始化入口
│   ├── agents/                   # AI智能体核心模块
│   │   ├── workflow.py         # LangGraph工作流编排
│   │   ├── state.py            # Agent状态类型定义
│   │   └── prompts.py          # 系统提示词模板
│   ├── models/                   # AI模型封装
│   │   ├── chat.py             # LLM调用封装
│   │   ├── embedding.py         # 嵌入模型封装
│   │   └── config.py           # 多provider配置
│   ├── memory/                   # 记忆模块
│   │   ├── memory.py           # MemoryModule调度层
│   │   └── memory_bank.py      # MemoryBank后端（分层记忆）
│   ├── storage/                  # 存储模块
│   │   ├── json_store.py       # JSON文件存储
│   │   └── init_data.py        # 数据初始化
│   ├── experiment/               # 实验对比模块
│   │   ├── runner.py           # 实验运行器
│   │   ├── test_data.py        # 测试数据生成器
│   │   └── loaders/            # 数据集加载器
│   │       ├── sgd_calendar.py # SGD-Calendar数据集
│   │       └── scheduler.py    # Scheduler数据集
│   └── api/                     # FastAPI接口
│       └── main.py              # REST API
├── config/                       # 配置文件
│   ├── scenarios.json           # 驾驶场景模板
│   ├── driver_states.json      # 驾驶员状态配置
│   └── evaluation_config.json   # 评估配置
├── data/                         # 数据目录（运行时生成）
├── tests/                        # 集成测试
│   ├── test_api.py             # API端点测试
│   ├── test_chat.py            # Chat→Memory→Workflow集成测试
│   ├── test_embedding.py       # Embedding→Memory检索集成测试
│   ├── test_memory_bank.py     # MemoryBank分层记忆测试
│   └── test_storage.py         # Storage→Memory持久化测试
├── webui/                        # Web界面
│   └── index.html              # 单页应用
├── main.py                       # Web服务入口
├── run_exp.py                    # 实验运行脚本
├── test_run.py                   # 快速测试脚本
└── pyproject.toml               # 项目配置
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

#### 评估指标

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| `avg_latency_ms` | 平均响应延迟 | 毫秒 |
| `task_completion_rate` | 任务完成率 | 成功数/总数 |
| `semantic_accuracy` | 语义理解准确率 | 意图匹配40% + 否定处理20% + 关键词重叠40% |
| `context_relatedness` | 上下文相关度 | 任务相关概念命中数/总概念数 |

#### 数据集加载器

- **SGD-Calendar** (`app/experiment/loaders/sgd_calendar.py`)
  - 来源：`vidhikatkoria/SGD_Calendar` (HuggingFace)
  - 提取 User: 开头的对话轮次
  - 最大60条测试用例

- **Scheduler** (`app/experiment/loaders/scheduler.py`)
  - 来源：`shawnha/scheduler_dataset` (HuggingFace)
  - 类型推断：flight_booking / hotel_booking / schedule_check / general

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
- DeepSeek API Key 或其他 OpenAI 兼容 API Key

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
# Linux/macOS
export DEEPSEEK_API_KEY="your-api-key"

# Windows (PowerShell)
$env:DEEPSEEK_API_KEY="your-api-key"
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
python run_exp.py
```

---

## API文档

启动服务后访问：

- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

---

## 配置说明

### 模型配置 (`app/models/config.py`)

支持多Provider配置：

```python
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-sonnet-20240229",
    },
}
```

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

| 文件 | 测试内容 | 引用模块 |
|------|----------|----------|
| `test_api.py` | API端点集成测试 | API→Workflow→Memory→Chat |
| `test_chat.py` | Chat驱动LLM记忆搜索、Workflow上下文注入 | Chat→Memory→Workflow |
| `test_embedding.py` | Embedding语义检索、MemoryBank检索与聚合 | Embedding→MemoryModule→MemoryBankBackend |
| `test_memory_bank.py` | 遗忘曲线检索、层级摘要、交互写入与聚合 | MemoryBankBackend→JSONStore, MemoryModule |
| `test_storage.py` | 跨实例持久化、反馈策略更新 | MemoryModule→init_storage→JSONStore |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web框架** | FastAPI + Uvicorn |
| **AI工作流** | LangChain + LangGraph |
| **LLM支持** | DeepSeek-chat, GPT-4, Claude-3 (OpenAI兼容接口) |
| **嵌入模型** | BGE-small-zh-v1.5 (HuggingFace) |
| **记忆系统** | MemoryBank (Ebbinghaus遗忘曲线 + 分层摘要) |
| **数据存储** | JSON文件 (标准库json) |
| **数据集** | HuggingFace Datasets |
| **开发工具** | uv (包管理), pytest (测试), ruff (lint), ty (类型检查) |

---

## License

MIT
