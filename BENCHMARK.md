# 基准测试

基于 [VehicleMemBench](vendor/VehicleMemBench/README.md) 的车载记忆基准评估框架。

详细实验说明请参见 [BENCHMARK-VehicleMemBench.md](BENCHMARK-VehicleMemBench.md)。

## 运行方式

### 前置条件

1. **配置模型**：确保 `config/llm.toml` 中 `model_groups.benchmark` 已配置有效模型
2. **设置 API 密钥**：如使用远程模型，导出所需环境变量（如 `DEEPSEEK_API_KEY`）；本地模型无需配置
3. **初始化子模块**：`git submodule update --init --recursive`

### 命令示例

```bash
# 全流程（建议先小范围测试）
uv run python run_benchmark.py all --file-range 1-2

# 分阶段运行
uv run python run_benchmark.py prepare --file-range 1-2
uv run python run_benchmark.py run --file-range 1-2

# 生成报告
uv run python run_benchmark.py report
uv run python run_benchmark.py report --output path/to/report.json
```

### CLI 参数

| 参数 | 默认值 | 适用命令 | 说明 |
|------|--------|----------|------|
| `--file-range` | `1-50` | prepare, run, all | 评估文件范围（如 `1-10` 或 `1,3,5`） |
| `--memory-types` | `none,gold,kv,memory_bank` | prepare, run, all | 记忆类型（逗号分隔） |
| `--reflect-num` | `10` | run, all | 反射推理次数 |
| `--allow-partial` | `false` | all | 即使部分步骤失败也生成报告 |
| `--output` | `None` | all, report | 自定义 JSON 报告输出路径（Markdown 报告自动生成至同目录） |

### 架构：策略模式

`vendor_adapter/VehicleMemBench/strategies/` 采用策略模式组织各记忆类型的评估逻辑：

| 策略 | 类名 | 说明 |
|------|------|------|
| `none` | `NoneStrategy` | 无记忆基线，直接调用 agent |
| `gold` | `GoldStrategy` | 黄金记忆，注入 ground truth |
| `kv` | `KvMemoryStrategy` | 键值存储，LLM 构建结构化记忆 |
| `memory_bank` | `MemoryBankStrategy` | 本项目 MemoryBank 后端（嵌入+摘要） |

每个策略实现 `MemoryStrategy` Protocol，统一 prepare → create_evaluator 流程。

> **注意**：VehicleMemBench 上游框架还支持 `summary` 类型，本项目适配器未实现。本项目 `kv` 策略对应上游框架的 `key_value` 类型。详见 [BENCHMARK-VehicleMemBench.md](BENCHMARK-VehicleMemBench.md)。

### 报告生成

`report` 命令收集 `data/benchmark/` 下的评估结果，先生成 JSON 报告（可通过 `--output` 自定义路径），再基于其生成 Markdown 报告至同目录，包含：
- 各记忆类型的 Exact Match Rate、Field-Level / Value-Level 指标
- 按推理类型分组的细分统计
- 效率指标（平均工具调用数、平均输出 token 数）

### 注意事项

- **API 限流**：大批量文件（如 1-50）可能触发 API 限流，建议分批处理
- **memory_bank 耗时**：`memory_bank` prepare 阶段对大历史文件较慢，需要对每条历史进行嵌入向量计算
- **gold/none 类型**：`gold`/`none` 的 prepare 阶段仅创建目录，无 prep.json 文件
- **并发控制**：通过 `BENCHMARK_QUERY_CONCURRENCY` 环境变量控制查询并发数（默认 4）

## 故障排除

**API错误（如529、429）**：
- 原因：API服务负载过高或达到速率限制
- 解决：减少并发（设置 `BENCHMARK_QUERY_CONCURRENCY=2`），或分批处理文件

**memory_bank prepare超时**：
- 原因：大历史文件需要多次LLM调用进行摘要和嵌入
- 解决：正常现象，耐心等待；或先测试小文件（如 `--file-range 1-1`）

**找不到历史文件**：
- 原因：VehicleMemBench子模块未初始化
- 解决：运行 `git submodule update --init --recursive`

**配置错误（ValueError: model_groups.benchmark must be configured）**：
- 原因：`config/llm.toml` 缺少 `model_groups.benchmark` 配置
- 解决：在配置文件中添加benchmark模型组配置
