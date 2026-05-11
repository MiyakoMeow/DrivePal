# 知行车秘（DrivePal）

本科生毕设。车载AI智能体原型系统。

## 项目配置

Python 3.14 + `uv`。

## 技术栈

| 类别 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| API层 | Strawberry GraphQL (code-first) |
| AI工作流 | 自定义四Agent流水线 + 轻量规则引擎 |
| LLM | DeepSeek, GLM (智谱), 可扩展 provider (TOML 配置) |
| Embedding | BGE-M3 (OpenRouter, 纯远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus遗忘曲线) |
| 存储 | TOML (tomllib + tomli-w) + JSONL |
| 开发 | uv, pytest (asyncio_mode=auto), ruff, ty |

## 目录索引

| 目录 | 说明 |
|------|------|
| `app/agents/` | Agent核心模块：工作流、规则引擎、概率推断 |
| `app/api/` | GraphQL API层：schema、resolvers、生命周期 |
| `app/memory/` | 记忆系统：MemoryBank、FAISS、遗忘曲线 |
| `app/models/` | AI模型封装：LLM/Embedding调用、fallback |
| `app/schemas/` | 驾驶上下文数据模型 |
| `app/storage/` | 存储引擎：TOML/JSONL |
| `tests/` | 测试：pytest、conftest、CI |
| `config/` | 模型/规则配置 |
| `experiments/` | 消融实验 |
| `archive/` | 归档：论文初稿等 |
| `webui/` | 模拟测试工作台 |

各目录内有 `AGENTS.md` 详述本模块。

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

`ty.toml`，rules all=error，`replace-imports-with-any = ["faiss", "docx"]`。

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

| 层 | 异常类 | 触发条件 |
|----|--------|----------|
| GraphQL | `InternalServerError` | 未预期的服务器错误 |
| GraphQL | `GraphQLInvalidActionError` | feedback action 非 accept/ignore |
| GraphQL | `GraphQLEventNotFoundError` | 事件 ID 不存在 |
| 记忆 | `MemoryBankError` → `TransientError`/`FatalError` | MemoryBank 异常基类（三层） |
| 记忆 | `LLMCallFailedError` | LLM API 调用失败（瞬态，可重试） |
| 记忆 | `SummarizationEmpty` | LLM 返回空内容（哨兵异常，非错误） |
| 记忆 | `IndexIntegrityError` | FAISS 索引文件损坏（永久） |
| 记忆 | `ConfigError` | 配置错误（永久） |
| 存储 | `AppendError` / `UpdateError` | TOMLStore 类型不匹配 |
| 模型 | `ProviderNotFoundError` | 引用字符串中 provider 未配置 |
| 模型 | `ModelGroupNotFoundError` | 引用字符串中 model_group 未配置 |

GraphQL 异常继承 `graphql.error.GraphQLError`，自动转为标准 GraphQL error response。其余异常由上层调用方处理。

## 关键阈值速查

| 阈值 | 值 | 位置 |
|------|-----|------|
| SOFT_FORGET_THRESHOLD | 0.3 | memory_bank/config.py |
| FORGET_INTERVAL_SECONDS | 300 | memory_bank/config.py |
| EMBEDDING_MIN_SIMILARITY | 0.3 | memory_bank/config.py |
| COARSE_SEARCH_FACTOR | 4 | memory_bank/config.py |
| RETRIEVAL_ALPHA | 0.7 | memory_bank/config.py |
| BM25_FALLBACK_THRESHOLD | 0.5 | memory_bank/config.py |
| CHUNK_SIZE_MIN/MAX | 200/8192 | memory_bank/config.py |
| MAX_MEMORY_STRENGTH | 10 | memory_bank/config.py |
| FORGETTING_TIME_SCALE | 1.0 | memory_bank/config.py |
| HTTP read timeout | 12h | models/_http.py |
| Embedding batch size | 100 | memory_bank/config.py |
| LLM max retries | 3 | memory_bank/config.py |
| SAVE_INTERVAL_SECONDS | 30 | memory_bank/config.py |
| LLM_TEMPERATURE/MAX_TOKENS | 0.3/400 | memory_bank/summarizer.py |

## Benchmark 外部项目

基准测试已独立为 [MiyakoMeow/VehicleMemBench](https://github.com/MiyakoMeow/VehicleMemBench)，提供 50 组数据集、23 车辆模块模拟器、五类记忆策略对比。MemoryBank 实现已对齐（确定性遗忘种子、参考日期、说话人感知检索等），可直接运行对照实验。

## 参考文献

- **MemoryBank**: Zhong et al. NeurIPS 2023. [arxiv-2305.10250](https://arxiv.org/abs/2305.10250)
- **VehicleMemBench**: Chen et al. 2026. [arxiv-2603.23840](https://arxiv.org/abs/2603.23840)
