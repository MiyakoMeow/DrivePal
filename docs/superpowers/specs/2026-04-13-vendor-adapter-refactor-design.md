# vendor_adapter 重构设计：统一策略模式 + 文件拆分

## 背景

`runner.py` 有 731 行，承担了至少 8 个职责：路径管理、数据加载、prepare 编排、run 编排、评估执行、结果收集、报告生成、搜索客户端构建。新增 memory_type 需要直接修改 runner 内部的 if/elif 分发逻辑。

## 目标

1. 将 runner.py 拆分为职责单一的小文件
2. 引入统一的 MemoryStrategy Protocol，使新增 memory_type 只需添加一个文件
3. 消除 prepare/run 之间的重复编排模式
4. 保持公共 API（prepare, run, report）不变

## 文件结构

```
vendor_adapter/VehicleMemBench/
├── __init__.py              # BenchMemoryMode（不变）
├── model_config.py          # 不变
├── paths.py                 # 路径常量 + 工具函数
├── loader.py                # QA/历史/prep 数据加载
├── strategies/
│   ├── __init__.py          # MemoryStrategy Protocol + STRATEGIES 注册表
│   ├── common.py            # StoreClient, format_search_results, history_to_interaction_records
│   ├── none.py              # NoneStrategy
│   ├── gold.py              # GoldStrategy
│   ├── kv.py                # KvMemoryStrategy
│   └── memory_bank.py       # MemoryBankStrategy
├── runner.py                # 编排逻辑（~200行）
└── reporter.py              # 结果收集 + 报告生成
```

现有 `memory_adapters/` 目录合并入 `strategies/`。

## MemoryStrategy Protocol

```python
class MemoryStrategy(Protocol):
    @property
    def mode(self) -> BenchMemoryMode: ...

    def needs_history(self) -> bool:
        """prepare 阶段是否需要历史文本."""

    def needs_agent_for_prep(self) -> bool:
        """prepare 阶段是否需要 agent client."""

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        """准备阶段：返回 prep 数据字典（序列化为 prep.json）."""

    async def evaluate(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        task: dict,
        task_id: int,
        gold_memory: str,
        reflect_num: int,
        file_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> dict | None:
        """评估阶段：执行单个 query 评估."""
```

### STRATEGIES 注册表

```python
STRATEGIES: dict[BenchMemoryMode, MemoryStrategy] = {
    s.mode: s for s in [NoneStrategy(), GoldStrategy(), KvMemoryStrategy(), MemoryBankStrategy()]
}
```

## 策略实现

### NoneStrategy

- `needs_history()`: False
- `needs_agent_for_prep()`: False
- `prepare()`: 返回 None
- `evaluate()`: `await asyncio.to_thread(process_task_direct, {**task, "history_text": ""}, task_id, agent_client, reflect_num)`

### GoldStrategy

- `needs_history()`: False
- `needs_agent_for_prep()`: False
- `prepare()`: 返回 None
- `evaluate()`: `await asyncio.to_thread(process_task_direct, {**task, "history_text": gold_memory}, task_id, agent_client, reflect_num)`

### KvMemoryStrategy

- `needs_history()`: True
- `needs_agent_for_prep()`: True
- `prepare()`: 调用 `split_history_by_day` + `build_memory_key_value`，返回 `{"type": KV, "store": store.to_dict()}`
- `evaluate()`: 从 prep_data 重建 VMBMemoryStore，调用 `process_task_with_kv_memory`

### MemoryBankStrategy

- `needs_history()`: True
- `needs_agent_for_prep()`: False
- `prepare()`: 使用 MemoryBankAdapter 构建存储到 `output_dir/store`，返回 `{"type": MEMORY_BANK, "data_dir": str(store_dir)}`
- `evaluate()`: 从 prep_data.data_dir 加载存储，构建 StoreClient，使用 `_make_sync_memory_search` 包装后调用 `_run_vehicle_task_evaluation`
- 含 `_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION` 和 `_CUSTOM_ADAPTER_INITIAL_TOOLS` 常量
- 含 `_make_sync_memory_search()` 辅助函数

## 各文件职责

### paths.py (~40行)

- `PROJECT_ROOT`, `VENDOR_DIR`, `BENCHMARK_DIR`, `OUTPUT_DIR` 常量
- `setup_vehiclemembench_path()` — 将 vendor 路径加入 sys.path
- `file_output_dir()`, `prep_path()`, `query_result_path()`, `ensure_output_dir()`

### loader.py (~80行)

- `load_qa(file_num)` — 加载 QA JSON
- `load_history(file_num)` — 加载历史文本
- `load_history_cache(file_nums, types)` — 批量加载历史，按 needs_history 过滤
- `load_prep(file_num, mtype)` — 加载单个 prep 数据
- `load_prep_cache(file_nums, types)` — 批量加载 prep
- `load_qa_safe(file_num)` — 安全加载 QA

### runner.py (~200行)

- `parse_file_range()`, `_parse_memory_types()` — 参数解析
- `EvalContext` dataclass — file 级评估上下文（runner 内部使用）
- `prepare()` — 遍历 (fnum, mtype)，调用 strategy.prepare()，写入 prep.json
- `run()` — 遍历 (fnum, mtype)，调用 strategy.evaluate()，写入 query 结果
- `_run_single()` — 单文件 query 级并发 + 结果持久化 + 错误处理

### reporter.py (~80行)

- `collect_results()` — 从 OUTPUT_DIR 收集 query_*.json
- `build_report_metrics()` — 构建指标
- `compute_memory_scores()` — 相对 GOLD 的 memory_score
- `report()` — 生成报告 + 打印

## 数据流

### Prepare

```
runner.prepare(file_range, memory_types)
  ├─ parse_file_range() → file_nums
  ├─ _parse_memory_types() → types
  ├─ 加载 history_cache（按需：strategies[mode].needs_history()）
  ├─ 解析 agent_client（按需：strategies[mode].needs_agent_for_prep()）
  └─ asyncio.gather(
       strategy.prepare(history_text, output_dir, agent_client?, semaphore)
       → 写入 prep.json
     )
```

### Run

```
runner.run(file_range, memory_types, reflect_num)
  ├─ 解析参数，获取 agent_client
  ├─ 加载 qa_cache + prep_cache
  └─ asyncio.gather(
       对每个 (fnum, mtype):
         ├─ 加载 prep_data, qa_data
         └─ _run_single():
              asyncio.gather(
                strategy.evaluate(agent_client, prep_data, task, ...)
                → 写入 query_{idx}.json
              )
     )
```

### Report

```
reporter.report(output_path?)
  ├─ collect_results() → {mtype: [results]}
  ├─ build_report_metrics() → 指标
  ├─ compute_memory_scores() → memory_score
  └─ 写入 report.json + 打印
```

## 测试

- `tests/test_vendor_adapter/test_common.py` — import 路径调整为 `strategies.common`
- `tests/test_vendor_adapter/test_model_config.py` — 不变
- `tests/test_vendor_adapter/test_runner.py` — mock 路径调整，逻辑不变
- `tests/test_vendor_adapter/test_strategies.py` — 新增：验证每个 Strategy 的属性和行为

## 不在范围内

- 不修改 `vendor/` 下的上游代码
- 不修改 `run_benchmark.py` 入口
- 不修改 `model_config.py`
- 不重构 vendor 的 evaluation 函数（process_task_direct 等）
