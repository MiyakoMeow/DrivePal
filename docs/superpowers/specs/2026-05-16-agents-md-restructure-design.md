# AGENTS.md 全量重组设计

## 动机

14 个 AGENTS.md 文档存在以下结构性问题：
1. `app/AGENTS.md` 与 root AGENTS.md 的"结构"节内容重复
2. 异常范式全局模式在各模块文档多次复述
3. `app/schemas/AGENTS.md` 仅 17 行，可合并入 api 文档
4. 各模块文档结构不统一（深度参差、章节顺序随机）

## 目标

1. 消除冗余，减少维护负担
2. 统一模块文档模板，信息可预测定位
3. 仅 root 一处定义全局模式，模块只记自有异常

## 变更清单

### 1. root AGENTS.md — 合并 app/ 索引表

将 `app/AGENTS.md` 的模块职责表合并入 root AGENTS.md 的"结构"节，替换当前仅列目录名的简单 mermaid。`app/AGENTS.md` 删除。

### 2. 异常描述去重

各模块文档中关于全局异常范式（AppError 基类、Transient/Fatal 二分、API 多重继承桥接、哨兵模式、不跨层原则）的描述删除，仅在 root AGENTS.md"异常处理范式"节保留完整定义。

具体删除内容：

| 模块 | 删除 | 保留 |
|------|------|------|
| agents | `AppError(catch)` 解释行 | WorkflowError 表 + 具体 catch 模式 |
| memory | Transient/Fatal 继承树 mermaid | MemoryBankError + SummarizationEmpty + catch |
| scheduler | "不跨层原则"段落 | tick 内 try/except 具体模式 |
| tools | AppError/WorkflowError 通用 catch 解释 | ToolExecutionError 及其专用 catch |
| api | AppError 全局范式（已在 root） | safe_call() 映射 + HTTP Code 映射 |
| models | AppError 子类全局说明 | 自有异常表 + 独立异常（ValueError/KeyError 子类）|
| voice | 无变化 | — |
| storage | 无变化 | — |

### 3. api + schemas 合并

删除 `app/schemas/AGENTS.md`。将 DrivingContext / DriverState / GeoLocation / SpatioTemporalContext / TrafficCondition / ScenarioPreset / ProcessQueryRequest / ProcessQueryResult 的模型定义并入 `app/api/AGENTS.md` 的新增"数据模型"节。

### 4. 模块文档统一模板

每个模块文档按以下章节顺序重新组织：

```
# 模块名
`路径/` — 一句话职责。

## 架构
mermaid 或文字数据流

## 组件
文件/类/职责表

## 关键类/接口
公开 API 签名

## 配置
对应 TOML 结构

## 自有异常
仅本模块引入的异常类

## 阈值（如适用）
参数表

## 测试
测试目录/文件

## 其他模块特有节
（按需，如 agents 的"概率推断"、"快捷指令"等）
```

当前各模块模板适配度：

| 模块 | 当前行数 | 调整难度 | 需补 |
|------|---------|---------|------|
| agents | 181 | 低 — 已有架构/组件/异常/阈值 | 按模板重排章节顺序 |
| memory | 176 | 低 — 已有完整结构 | 删重复继承树 |
| scheduler | 143 | 低 — 结构已接近模板 | 轻微调整 |
| tools | 142 | 低 — 结构已接近模板 | 按模板调整 |
| api | 119 | 中 — 合并 schemas 后重排 | 新增"数据模型"节 |
| voice | 105 | 低 | 按模板确认章节 |
| models | 69 | 中 — 缺架构 mermaid | 补架构图 |
| storage | 80 | 中 — 缺架构 mermaid | 补架构图 |

### 5. 其他文件

- `tests/AGENTS.md` — 无变更
- `experiments/ablation/AGENTS.md` — 无变更
- `archive/AGENTS.md` — 无变更

## 执行顺序

1. 删除 `app/AGENTS.md`，合并内容入 root
2. 删除 `app/schemas/AGENTS.md`，合并内容入 api
3. 逐模块按模板重排（agents → memory → scheduler → tools → voice → api → models → storage）
4. root AGENTS.md 异常节验证（删除已在模块中去重的内容）
5. 最终校验

### 最终校验清单

- [ ] 无文件残留（app/AGENTS.md 和 app/schemas/AGENTS.md 已删除）
- [ ] root AGENTS.md 中所有 cross-ref 指向正确（如 `→ app/agents/AGENTS.md`）
- [ ] 各模块文档 mermaid 图引用路径未断链
- [ ] `uv run ruff check --fix` 通过
- [ ] `uv run ruff format --check` 通过
- [ ] `uv run ty check` 通过
- [ ] `uv run pytest` 通过

## 排除范围

- 不修改代码实现
- 不修改 mermaid 图的内容（仅调整位置）
- 不修改实际技术描述（仅调整组织方式）
