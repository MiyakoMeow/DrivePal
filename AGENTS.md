# 知行车秘

本科毕设。车载AI智能体原型。

> 各模块详文见子目录 `AGENTS.md`。

## 设计目标

### 核心问题

车载场景下，驾驶员需要在不分散注意力的情况下管理日程、接收提醒、查询信息。现有方案（纯语音助手/手机提醒）缺乏：

1. **驾驶情境感知** — 提醒内容和方式应随路况、疲劳度、乘客数动态调整
2. **长期记忆** — 能记住用户的偏好、历史事件和上下文相关关系
3. **被动记录** — 用户无需手动创建提醒，系统从语音中自动提取

### 设计目标

| 目标 | 说明 | 体现 |
|------|------|------|
| **驾驶安全优先** | 提醒方式受规则引擎约束，高速仅音频、疲劳时抑制非紧急提醒 | 7 条硬规则 + `postprocess_decision` 不可绕过 |
| **零配置记忆** | 语音自动转录 → MemoryBank，无需用户手动创建提醒 | `VoicePipeline` → `ProactiveScheduler` → `MemoryModule` |
| **情境感知** | 外部数据（位置/状态/路况）直接注入，跳过 LLM 编造 | `ProactiveScheduler.update_context()` / API 注入 `DrivingContext` |
| **可解释决策** | 三阶段工作流各节点输出可独立审查 | `WorkflowStages` 保留每阶段结果 |
| **遗忘曲线** | 记忆按 Ebbinghaus 曲线衰减，检索时按保留率加权 | `forgetting_retention()` |
| **静默降级** | 非核心模块（ASR/语音）缺失时系统继续运行 | 各模块 `try/except` + 空返回 |

## 系统设计

### 核心理念

系统围绕三条数据流构建，覆盖从感知到行动的全链路：

```
感知层（语音/上下文） → 决策层（AgentWorkflow + 规则引擎） → 行动层（输出/工具/提醒）
```

三条数据流共享同一决策核心，但在触发方式上解耦：

```mermaid
flowchart LR
    subgraph Passive["被动流"]
        A1["语音输入"] -->|VAD→ASR| M1["MemoryBank"]
    end
    subgraph Reactive["响应流"]
        A2["用户查询"] -->|REST/WS| WF["AgentWorkflow"]
        M1 -->|检索| WF
        WF -->|回复| A2
    end
    subgraph Proactive["主动流"]
        S["Scheduler"] -->|5 种触发源| WF
        WF -->|提醒| U["WS 推送"]
    end
```

### 架构原则

| 原则 | 体现 |
|------|------|
| **安全不可绕过** | 规则引擎后处理 `postprocess_decision()` 在 LLM 输出后强制执行，所有输出路径必经 |
| **异常不跨层** | 下层抛特定异常，上层 catch 兜底。scheduler tick 内各步骤独立 try/except |
| **配置数据驱动** | 规则/快捷指令/模型参数/语音/调度/工具均 TOML 配置，代码不耦合具体值 |
| **可观测性** | 三阶段工作流各节点输出独立审查；scheduler 每步日志；MemoryBank Metrics |
| **静默降级** | 语音模块/ASR 模型缺失时不阻塞系统，仅返回空文本 |

## 关键抽象关系

```mermaid
flowchart LR
    subgraph AW[AgentWorkflow 决策核心]
        direction TB
        AWI[接收: user_query / context_override / ShortcutResolver]
        AWO[产出: MultiFormatContent + PendingReminder + tool_calls]
        AWD[依赖: MemoryModule / ChatModel / RuleEngine / ToolExecutor]
    end
    subgraph PS[ProactiveScheduler 主动调度]
        direction TB
        PSI[输入: VoicePipeline / update_context]
        PSE[引擎: ContextMonitor → MemoryScanner → TriggerEvaluator]
        PSO[输出: proactive_run + WS broadcast]
    end
    subgraph VP[VoicePipeline 语音感知]
        direction TB
        VPI[输入: VoiceRecorder / audio frames]
        VPP[处理: VADEngine → SherpaOnnxASREngine]
        VPO[输出: on_transcription → Scheduler.push_voice_text]
    end
    subgraph MM[MemoryModule 记忆管理]
        direction TB
        MMW[写入: MemoryEvent]
        MMR[读取: search → SearchResult]
        MMB[后台: finalize → 分层摘要 + Ebbinghaus]
    end
```

## 环境

Python 3.14 + `uv`。

## 技术栈

| 类 | 术 |
|----|----|
| Web | FastAPI + Uvicorn |
| AI流水线 | 三阶段工作流（Context → JointDecision → Execution）+ 规则引擎 |
| LLM | DeepSeek |
| Embedding | BGE-M3 (OpenRouter, 远程) |
| 记忆 | MemoryBank (FAISS + Ebbinghaus) |
| 语音 | sherpa-onnx (SenseVoice) + webrtcvad |
| 存储 | TOML + JSONL |
| 开发 | uv, pytest(asyncio_mode=auto), ruff, ty |

## 结构

```mermaid
flowchart LR
    subgraph Root["项目根"]
        M["main.py"]
    end
    subgraph App["app/"]
        A1["agents/ → AGENTS.md"]
        A2["voice/ （语音流水线）"]
        A3["scheduler/ （主动调度器）"]
        A4["tools/ （工具框架）"]
        A5["api/ → AGENTS.md"]
        A6["models/ → AGENTS.md"]
        A7["memory/ → AGENTS.md"]
        A9["storage/ → AGENTS.md"]
        AC["config.py"]
    end
    subgraph Other["其他"]
        T["tests/ → AGENTS.md"]
        C["config/ （TOML配置）"]
        D["data/ （运行时数据）"]
        AR["archive/ → AGENTS.md"]
        E["experiments/ → AGENTS.md"]
    end
    M --> App
    M --> Other
```

> 注：A8 schemas/ 已合并入 api/AGENTS.md

| 子目录 | 职责 | 详文 |
|--------|------|------|
| agents/ | 工作流编排、规则引擎、概率推断、提示词 | agents/AGENTS.md |
| voice/ | 语音流水线（录音→VAD→ASR） | voice/AGENTS.md |
| scheduler/ | 主动调度器（后台轮询触发） | scheduler/AGENTS.md |
| tools/ | 工具调用框架 | tools/AGENTS.md |
| api/ | REST路由、WebSocket流式、服务生命周期、数据模型 | api/AGENTS.md |
| memory/ | MemoryBank(FAISS+Ebbinghaus)、隐私保护 | memory/AGENTS.md |
| models/ | LLM多provider fallback、Embedding | models/AGENTS.md |
| storage/ | TOML异步存储、JSONL追加写入 | storage/AGENTS.md |

`config.py` — 应用级配置（数据目录路径等）
`exceptions.py` — 全局异常基类 `AppError` 定义（`code + message`）
`utils.py` — 共享工具函数，含 `haversine()`（两点间球面距离，米）

## 检查

改后：
1. `uv run ruff check --fix`
2. `uv run ruff format`
3. `uv run ty check`

任务完：
4. `uv run pytest`

Python 3.14：`except ValueError, TypeError:` 乃 PEP-758 新语法。

### ruff

`ruff.toml`，extend-select=ALL，忽略 D203/D211/D213/D400/D415/D107/COM812/E501/RUF001-003 — D107: `__init__` 的 docstring 由类 docstring 覆盖。`tests/**` 豁免24条。

### ty

`ty.toml`，rules all=error，faiss/docx/pyaudio/sherpa_onnx → Any。

## 代码规范

- **注释**：中文，释 why 非 what
- **提交**：英文，Conventional Commits
- **内联抑制**：禁 `# noqa`/`# type:`/`# ty:`。修不了在 ruff.toml/ty.toml 忽略
- **函数**：一事一函数
- **嵌套**：小分支提前 return/continue/break
- **导入**：标准库→三方→内部→相对，空行分隔。禁通配
- **不可变**：const/final 优先
- **结构图**：mermaid 优先，禁 ASCII art 手绘结构图
- **测试**：一事一测。Given→When→Then。名含场景+期望
- **文档同步**：改实现时同步更新相关 `AGENTS.md`，旧内容对应淘汰，勿留过期文档

## 工作树

```bash
git worktree add .worktrees/<名> -b <名>
```

## 异常处理范式

`AppError(Exception)` 为全系统基类，统一 `code+message`。
各模块继承之，API 层多重继承桥接 FastAPI。

> 各模块异常详情 → `app/*/AGENTS.md`。

### 核心模式

| 模式 | 载体 | 说明 |
|------|------|------|
| **统一基类** | `AppError` | `code+message`，各模块继承 |
| **MemoryBank 可恢复二分** | `TransientError`/`FatalError` | TransientError 瞬态可重试 vs FatalError 永久不重试，仅 MemoryBank 实现 |
| **多重继承桥接** | API 层 `AppError` 同时继承域内 `AppError` + `HTTPException` | `isinstance` 双视角：域内代码见 `AppError`，FastAPI 见 `HTTPException` |
| **哨兵** | `SummarizationEmpty` | 非错误，控制流信号，调用方捕获返 None |
| **独立异常** | `ValueError`/`TypeError` 子类 | 类型校验/结构误用，不入继承树 |
| **不跨层** | 下层抛→上层 reinterpret | 各层包装本层类型再上抛 |

### 原则

1. 域内异常继承 `AppError`，类型校验继承内置
2. catch 后 reinterpret，不传播底层类型
3. 哨兵显式标注“非错误”
4. 沿用 Transient/Fatal 二分
5. 各模块具体异常 → 对应 `AGENTS.md`

## Benchmark

外部项目 MiyakoMeow/VehicleMemBench。50组数据集、23模块模拟器、五类记忆策略、A/B两组评测。本系统MemoryBank已与 VehicleMemBench 对齐。

参考文献 → `archive/AGENTS.md`。

## 未解决

### 功能缺口

1. **突发事件模块** — JointDecision + 规则引擎联合覆盖，无独立处理模块
2. **ASR Speaker ID / 唤醒词** — SenseVoice 支持情感/语言检测但未利用 Speaker Identification；无唤醒词检测，当前始终监听
3. **真实车辆 ContextProvider** — driving_context 由 WebUI/API 注入，无 CAN 总线/OBD 集成
4. **TTS 输出** — 输出层产出 `speakable_text` 但无 TTS 引擎接入，当前为文本展示
5. **多用户语音识别** — VoicePipeline 无 `user_id`，ASR 输出未关联驾驶员身份

### 架构待完善

6. **工具安全约束细化** — 当前 `postprocess_decision` 统一管辖所有工具，但未按工具类型差异化约束
7. **scheduler per-user 实例** — lifespan 仅初始化 default 用户，`_schedulers` dict 支持多用户但未实际启用
8. **集成测试** — voice/scheduler/tools 三模块单元测试覆盖不足，缺少集成测试

## 开发路线（建议）

| 阶段 | 内容 | 前置 |
|------|------|------|
| **短期** | TTS 引擎接入；集成测试补全；per-user scheduler 启用 | — |
| **中期** | 真实 ASR 模型优化（SenseVoice int8 量化已可用）；Wake Word 检测；工具安全约束细化 | 短期 |
| **长期** | 车辆 CAN 总线集成；OBD 数据接入；多模态（语音+视觉）输入 | 中期 |
