# 知行车秘

本科生毕设。车载AI智能体原型系统。

> 本文档为项目根总览。各模块详细文档已拆分至各自目录的 `AGENTS.md`。

## 文档索引

| 模块 | 路径 | 内容 |
|------|------|------|
| App 核心 | `app/AGENTS.md` | 各子模块索引与概述 |
| Agent 系统 | `app/agents/AGENTS.md` | Agent工作流、规则引擎、概率推断 |
| API 层 | `app/api/AGENTS.md` | GraphQL API、服务入口与生命周期 |
| 记忆系统 | `app/memory/AGENTS.md` | MemoryBank、记忆基础设施、隐私保护 |
| 模型封装 | `app/models/AGENTS.md` | LLM调用特性 |
| 模式定义 | `app/schemas/AGENTS.md` | 上下文数据模型 |
| 数据存储 | `app/storage/AGENTS.md` | TOML/JSONL 存储引擎 |
| 模型配置 | `config/AGENTS.md` | 模型配置格式、环境变量 |
| 测试 | `tests/AGENTS.md` | 测试运行命令、CI 工作流 |
| 实验 | `experiments/AGENTS.md` | 消融实验设计 |
| 论文 | `archive/AGENTS.md` | 论文参考文献 |

## 项目配置

Python 3.14 + `uv`。

## 环境配置参考

> 以下为当前开发机器上的目录布局，**不同机器路径不同**，仅作本地参考。

| 内容 | 路径 |
|------|------|
| 本仓库 | `~/Codes/DrivePal-2` |
| VehicleMemBench 基准测试 | `~/Codes/VehicleMemBench` |
| 论文 | `~/Papers/` |

## 技术栈

| 类别 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| API层 | Strawberry GraphQL (code-first) |
| AI工作流 | 自定义四Agent流水线 + 轻量规则引擎 |
| LLM | Qwen3.5-2B (vLLM), MiniMax-M2.5, DeepSeek, GLM-4.7-flashx |
| Embedding | BGE-M3 (vLLM, OpenAI兼容接口, 纯远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus遗忘曲线) |
| 存储 | TOML (tomllib + tomli-w) + JSONL |
| 开发 | uv, pytest (asyncio_mode=auto), ruff, ty |

## 项目结构

```
app/
├── agents/            # Agent核心模块 → app/agents/AGENTS.md
├── api/               # GraphQL API层 → app/api/AGENTS.md
├── models/            # AI模型封装 → app/models/AGENTS.md
├── memory/            # 记忆模块 → app/memory/AGENTS.md
├── schemas/           # 数据模型 → app/schemas/AGENTS.md
├── storage/           # 存储引擎 → app/storage/AGENTS.md
├── config.py          # 应用级配置
tests/                 # 测试 → tests/AGENTS.md
config/                # 模型/规则配置 → config/AGENTS.md
data/                  # 运行时数据
webui/                 # 模拟测试工作台
archive/               # 归档卷 → archive/AGENTS.md
experiments/           # 消融实验 → experiments/AGENTS.md
```

## 检查流程

每改后：
1. `uv run ruff check --fix`
2. `uv run ruff format`
3. `uv run ty check`

任务完：
4. `uv run pytest`

Python 3.14 注意：`except ValueError, TypeError:` 是 PEP-758 新语法，非 Python 2 残留。

### ruff 配置

`ruff.toml`，extend-select=ALL，忽略 D203/D211/D213/D400/D415/COM812/E501/RUF001-003。
`tests/**` 豁免 S101/S311/SLF001 等测试常见模式。

### ty 配置

`ty.toml`，rules all=error，faiss 替换为 Any。

## 代码规范

- **注释**：中文，解释 why 非 what
- **提交**：英文，Conventional Commits（feat/fix/docs/refactor）
- **内联抑制**：禁 `# noqa`、`# type:`。遇 lint/type 错误先修代码，修不了在 ruff.toml/ty.toml 按文件或全局忽略并注明原因
- **函数粒度**：一事一函数，超30行需理由
- **嵌套控制**：小分支提前 return/continue/break，复杂逻辑提取函数
- **导入顺序**：标准库 → 三方库 → 内部模块 → 相对导入，空行分隔。禁通配导入
- **不可变优先**：const/final 优先。新对象替换原地 mutate（性能关键路径可破）
- **测试**：一测试一事。Given → When → Then。名含场景+期望，描述用中文
- **设计原则**：单一职责、开闭、依赖倒置、接口隔离、迪米特。OOP 附加里氏替换

## 错误处理模式

项目使用分层异常设计：

| 层 | 异常类 | 触发条件 |
|----|--------|----------|
| GraphQL | `InternalServerError` | 未预期的服务器错误 |
| GraphQL | `GraphQLInvalidActionError` | feedback action 非 accept/ignore |
| GraphQL | `GraphQLEventNotFoundError` | 事件 ID 不存在 |
| 记忆 | `MemoryBankError` → `TransientError`/`FatalError` | MemoryBank 异常基类（三层） |
| 记忆 | `LLMCallFailed` | LLM API 调用失败（瞬态，可重试） |
| 记忆 | `SummarizationEmpty` | LLM 返回空内容（哨兵异常，非错误） |
| 记忆 | `EmbeddingFailed` | 嵌入 API 调用失败（瞬态） |
| 记忆 | `MetadataCorrupted` / `IndexIntegrityError` | 数据损坏（永久） |
| 记忆 | `InvalidActionError` | FeedbackData action 校验失败 |
| 存储 | `AppendError` / `UpdateError` | TOMLStore 类型不匹配 |
| 模型 | `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| 模型 | `ModelGroupNotFoundError` | 引用字符串中 model_group 未配置 |

GraphQL 异常继承 `graphql.error.GraphQLError`，自动转为标准 GraphQL error response。
其余异常由上层调用方处理，不跨层泄露实现细节。

反馈学习机制见 [app/api/AGENTS.md](app/api/AGENTS.md)。

## 关键阈值速查

| 阈值 | 值 | 位置 |
|------|-----|------|
| SOFT_FORGET_THRESHOLD | 0.3 | config.py |
| FORGET_INTERVAL_SECONDS | 300 | config.py |
| FORGETTING_TIME_SCALE | 1 | config.py |
| EMBEDDING_MIN_SIMILARITY | 0.3 | config.py |
| COARSE_SEARCH_FACTOR | 4 | retrieval.py |
| AGGREGATION_SIMILARITY_THRESHOLD | 0.8 | retrieval.py |
| OVERLAP_RATIO_THRESHOLD | 0.45 | retrieval.py |
| DEFAULT_CHUNK_SIZE | 1500（自适应回退值） | retrieval.py |
| CHUNK_SIZE_MIN | 200 | config.py |
| CHUNK_SIZE_MAX | 8192 | config.py |
| HTTP read timeout | 12h | _http.py |
| Embedding batch size | 100 | embedding.py |
| Embedding retry | 3次 | embedding.py |
| SAVE_INTERVAL_SECONDS | 30 | config.py |
| LLM_TEMPERATURE (摘要) | 0.3 | summarizer.py |
| LLM_MAX_TOKENS (摘要) | 400 | summarizer.py |
| REFERENCE_DATE_OFFSET | 1天 | index.py |

## Benchmark

基准测试已从本仓库移除（commit `fbe453b`），独立为外部项目 MiyakoMeow/VehicleMemBench。

VehicleMemBench 提供：
- 50 组数据集（`benchmark/qa_data/qa_{1..50}.json` + `benchmark/history/history_{1..50}.txt`）
- 23 个车辆模块模拟器（`environment/`）
- 五类记忆策略：None（零样本）、Gold（理论上限）、Summary（递归摘要）、Key-Value（键值存储）、MemoryBank（本系统方案）
- 评测指标：Exact State Match、Field-level P/R/F1、Value-level P/R/F1、Tool Call Count
- 模型评估（A 组，评估 backbone 模型）+ 内存系统评估（B 组，含第三方系统 Mem0/MemOS/LightMem/Supermemory/Memobase）

本项目的 MemoryBank 实现已与 VehicleMemBench 对齐（确定性遗忘种子、参考日期、说话人感知检索等），可直接在 VehicleMemBench 中运行对照实验。

参考文献清单见 [archive/AGENTS.md](archive/AGENTS.md)。

## 未解决问题

1. 突发事件处理：由 Strategy Agent 语义推理 + 规则引擎联合覆盖（无独立模块），论文中说明此设计决策
