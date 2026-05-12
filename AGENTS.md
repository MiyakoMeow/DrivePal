# 知行车秘

本科生毕设。车载AI智能体原型系统。

> 本文档为项目根总览。各模块详细文档已拆分至各自目录的 `AGENTS.md`。

## 项目配置

Python 3.14 + `uv`。

## 环境配置参考

> 以下为当前开发机器上的目录布局，**不同机器路径不同**，仅作本地参考。

| 内容 | 路径 |
|------|------|
| 本仓库 | `~/Codes/DrivePal` |
| VehicleMemBench 基准测试 | `~/Codes/VehicleMemBench` |
| 论文 | `~/Papers/` |

## 技术栈

| 类别 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| API层 | Strawberry GraphQL (code-first) |
| AI工作流 | 自定义四Agent流水线 + 轻量规则引擎 |
| LLM | DeepSeek, GLM-4.5-air |
| Embedding | BGE-M3 (vLLM, OpenAI兼容接口, 纯远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus遗忘曲线) |
| 存储 | TOML (tomllib + tomli-w) + JSONL |
| 开发 | uv, pytest (asyncio_mode=auto), ruff, ty |

## 项目结构

```
main.py                # Uvicorn 入口
app/
├── agents/            # Agent工作流、规则引擎、概率推断 → app/agents/AGENTS.md
├── api/               # GraphQL API、服务入口与生命周期、错误处理 → app/api/AGENTS.md
├── models/            # LLM调用特性、错误处理与阈值 → app/models/AGENTS.md
├── memory/            # MemoryBank、记忆基础设施、隐私保护、错误处理与阈值 → app/memory/AGENTS.md
├── schemas/           # 上下文数据模型 → app/schemas/AGENTS.md
├── storage/           # TOML/JSONL 存储引擎、错误处理 → app/storage/AGENTS.md
├── config.py          # 应用级配置
├── AGENTS.md           # 应用层文档
tests/                 # 测试运行命令、CI 工作流 → tests/AGENTS.md
config/                # 模型配置格式、环境变量、完整配置项 → config/AGENTS.md
data/                  # 运行时数据
scripts/               # 工具脚本
webui/                 # 模拟测试工作台
archive/               # 论文参考文献 → archive/AGENTS.md
experiments/           # 消融实验设计 → experiments/AGENTS.md
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

`ty.toml`，rules all=error，faiss/docx 替换为 Any。

## 代码规范

- **注释**：中文，解释 why 非 what
- **提交**：英文，Conventional Commits（feat/fix/docs/refactor）
- **内联抑制**：禁 `# noqa`、`# type:`。遇 lint/type 错误先修代码，修不了在 ruff.toml/ty.toml 按文件或全局忽略并注明原因
- **函数粒度**：一事一函数，长度遵循 ruff 检查
- **嵌套控制**：小分支提前 return/continue/break，复杂逻辑提取函数
- **导入顺序**：标准库 → 三方库 → 内部模块 → 相对导入，空行分隔。禁通配导入
- **不可变优先**：const/final 优先。新对象替换原地 mutate（性能关键路径可破）
- **测试**：一测试一事。Given → When → Then。名含场景+期望，描述用中文

## 工作树

`.worktrees/` 用于隔离开发。已在 `.gitignore`，内容不入仓库。
```
git worktree add .worktrees/<分支名> -b <分支名>
```

## 错误处理模式

各层异常定义见对应模块文档：

- **API 层**：GraphQL 异常 → [app/api/AGENTS.md](app/api/AGENTS.md)
- **记忆系统**：MemoryBank 分层异常 → [app/memory/AGENTS.md](app/memory/AGENTS.md)
- **数据存储**：`AppendError` / `UpdateError` → [app/storage/AGENTS.md](app/storage/AGENTS.md)
- **模型封装**：`ProviderNotFoundError` / `ModelGroupNotFoundError` → [app/models/AGENTS.md](app/models/AGENTS.md)

原则：异常由上层调用方处理，不跨层泄露实现细节。反馈学习机制见 [app/api/AGENTS.md](app/api/AGENTS.md)。

## 关键阈值速查

各模块关键阈值见对应文档：

- **记忆系统**：MemoryBank 阈值（遗忘/检索/摘要/分块）→ [app/memory/AGENTS.md](app/memory/AGENTS.md)
- **模型封装**：HTTP timeout / embedding 参数 → [app/models/AGENTS.md](app/models/AGENTS.md)
- **完整环境变量**（含全部 MemoryBank 可配置项）→ [config/AGENTS.md](config/AGENTS.md)

## Benchmark

基准测试已从本仓库移除，独立为外部项目 MiyakoMeow/VehicleMemBench。

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
