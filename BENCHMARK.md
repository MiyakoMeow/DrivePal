# 对比实验

基于 [VehicleMemBench](vendor/VehicleMemBench/README.md) 的车载记忆基准评估框架。

详细实验说明请参见 [BENCHMARK-VehicleMemBench.md](BENCHMARK-VehicleMemBench.md)。

## 运行方式

### 前置条件

1. **配置模型**：确保 `config/llm.toml` 中 `model_groups.benchmark` 已配置有效模型
2. **设置API密钥**：导出所需环境变量（如 `MINIMAX_API_KEY`）
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
```

### CLI 参数

| 参数 | 默认值 | 适用命令 | 说明 |
|------|--------|----------|------|
| `--file-range` | `1-50` | prepare, run, all | 评估文件范围（如 `1-10` 或 `1,3,5`） |
| `--memory-types` | `gold,summary,kv,memory_bank` | prepare, run, all | 记忆类型 |
| `--reflect-num` | `10` | run, all | 反射推理次数 |
| `--allow-partial` | `false` | all | 即使部分步骤失败也生成报告 |
| `--output` | `None` | all, report | 自定义报告输出路径 |

### 注意事项

- **API限流**：大批量文件（如1-50）可能触发API限流，建议分批处理
- **memory_bank耗时**：memory_bank prepare阶段对大历史文件较慢，属正常现象
- **gold类型**：gold类型prepare阶段仅创建目录，无prep.json文件

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
