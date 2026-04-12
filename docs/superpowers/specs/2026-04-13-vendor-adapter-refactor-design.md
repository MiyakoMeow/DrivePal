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
├── paths.py                 # 路径常量 + 工具函数 + sys.path 初始化
├── loader.py                # QA/历史/prep 数据加载
├── strategies/
│   ├── __init__.py          # MemoryStrategy Protocol + QueryEvaluator Protocol + STRATEGIES 注册表 + VehicleMemBenchError
│   ├── common.py            # StoreClient, format_search_results, history_to_interaction_records
│   ├── none.py              # NoneStrategy
│   ├── gold.py              # GoldStrategy
│   ├── kv.py                # KvMemoryStrategy
│   └── memory_bank.py       # MemoryBankStrategy（含 memory_search 工具逻辑 + _make_sync_memory_search）
├── runner.py                # 编排逻辑（~200行）
└── reporter.py              # 结果收集 + 报告生成
```

现有 `memory_adapters/` 目录合并入 `strategies/`。

### 导入顺序约束

`paths.py` 中的 `setup_vehiclemembench_path()` 在模块加载时执行，将 vendor 路径加入 `sys.path`。所有 strategy 文件依赖 `evaluation.*` 系列的 vendor 导入，必须确保 `paths.py` 先于 strategy 被导入。通过在 strategy 文件顶部 `from ...paths import ...`（或 `import ...paths`）来保证初始化顺序。

### 常量与辅助函数位置映射

| 当前位置 | 目标位置 | 说明 |
|---------|---------|------|
| `runner.py:32-35` 路径常量 | `paths.py` | PROJECT_ROOT, VENDOR_DIR, BENCHMARK_DIR, OUTPUT_DIR |
| `runner.py:37-44` 环境变量 | `runner.py` | `_QUERY_CONCURRENCY_LIMIT` |
| `runner.py:42-44` 搜索超时 | `strategies/memory_bank.py` | `_SEARCH_TIMEOUT`（唯一使用者） |
| `runner.py:47-55` sys.path 设置 | `paths.py` | `setup_vehiclemembench_path()` + 模块级调用 |
| `runner.py:24-25` 异常类 | `strategies/__init__.py` | `VehicleMemBenchError` |
| `runner.py:57-70` vendor 导入 | 各 strategy 文件 | 按需导入 |
| `runner.py:92-126` 自定义工具定义 | `strategies/memory_bank.py` | 常量 |
| `runner.py:152-161` agent client 工厂 | `runner.py` | `_get_agent_client()` |
| `runner.py:577-617` sync memory search | `strategies/memory_bank.py` | `_make_sync_memory_search()` |

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

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> QueryEvaluator:
        """创建每文件评估器（含一次性初始化，如加载 store/构建 search client）."""
```

**设计要点：** `create_evaluator()` 将每文件初始化（加载存储、构建搜索客户端、捕获事件循环等）与每查询评估分离。每个 `(file_num, mtype)` 对调用一次，返回的 `QueryEvaluator` 在该文件的所有查询间复用。

### QueryEvaluator Protocol

```python
class QueryEvaluator(Protocol):
    async def evaluate(
        self,
        task: dict,
        task_id: int,
        gold_memory: str,
    ) -> dict | None:
        """评估单个 query（使用 create_evaluator 时已初始化的资源）."""
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
- `create_evaluator()`: 返回一个 evaluator，其 evaluate() 为：
  ```python
  async with query_semaphore:
      return await asyncio.to_thread(
          process_task_direct,
          {**task, "history_text": ""},
          task_id, agent_client, reflect_num,
      )
  ```

### GoldStrategy

- `needs_history()`: False
- `needs_agent_for_prep()`: False
- `prepare()`: 返回 None
- `create_evaluator()`: 返回一个 evaluator，其 evaluate() 为：
  ```python
  async with query_semaphore:
      return await asyncio.to_thread(
          process_task_direct,
          {**task, "history_text": gold_memory},
          task_id, agent_client, reflect_num,
      )
  ```

### KvMemoryStrategy

- `needs_history()`: True
- `needs_agent_for_prep()`: True
- `prepare()`: 调用 `split_history_by_day` + `build_memory_key_value`，返回 `{"type": KV, "store": store.to_dict()}`
- `create_evaluator()`: 从 prep_data 重建 `VMBMemoryStore` 实例（每文件一次），返回 evaluator
- `evaluate()`: 使用已构建的 kv_store 调用 `process_task_with_kv_memory`，受 query_semaphore 控制

### MemoryBankStrategy

- `needs_history()`: True
- `needs_agent_for_prep()`: False
- `prepare()`: 使用 MemoryBankAdapter 构建存储到 `output_dir/store`，返回 `{"type": MEMORY_BANK, "data_dir": str(store_dir)}`
- `create_evaluator()`:
  - 从 prep_data.data_dir 加载 MemoryBankStore（每文件一次，非每查询）
  - 构建 StoreClient
  - 调用 `_make_sync_memory_search(search_client)` 捕获事件循环引用（在 async 上下文中调用，确保 `get_running_loop()` 正确）
  - 返回持有这些资源的 evaluator
- `evaluate()`: 使用已构建的 memory_funcs 调用 `_run_vehicle_task_evaluation`，受 query_semaphore 控制
- 含 `_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION` 和 `_CUSTOM_ADAPTER_INITIAL_TOOLS` 常量
- 含 `_make_sync_memory_search()` 辅助函数（从 `common.py` 导入 `format_search_results`）
- 含 `_SEARCH_TIMEOUT` 常量（从 `os.environ.get("BENCHMARK_SEARCH_TIMEOUT", ...)` 读取）

## 各文件职责

### paths.py (~40行)

- `PROJECT_ROOT`, `VENDOR_DIR`, `BENCHMARK_DIR`, `OUTPUT_DIR` 常量
- `setup_vehiclemembench_path()` — 将 vendor 路径加入 sys.path
- 模块级调用 `setup_vehiclemembench_path()`（确保 import paths.py 时初始化）
- `file_output_dir()`, `prep_path()`, `query_result_path()`, `ensure_output_dir()`

### loader.py (~80行)

- `load_qa(file_num: int) -> dict` — 异步加载 QA JSON
- `load_history(file_num: int) -> str` — 异步加载历史文本
- `load_history_cache(file_nums: list[int], strategies: list[MemoryStrategy]) -> dict[int, str]` — 批量加载历史，按 needs_history 过滤
- `load_prep(fnum: int, mtype: BenchMemoryMode) -> tuple[BenchMemoryMode, int, dict | None]` — 加载单个 prep 数据
- `load_prep_cache(file_nums: list[int], types: list[BenchMemoryMode]) -> dict[tuple[BenchMemoryMode, int], dict | None]` — 批量加载 prep
- `load_qa_safe(fnum: int) -> tuple[int, dict | None]` — 安全加载 QA（FileNotFoundError → None）

### runner.py (~200行)

- `_QUERY_CONCURRENCY_LIMIT` 常量（从 `BENCHMARK_QUERY_CONCURRENCY` 环境变量读取）
- `parse_file_range()`, `_parse_memory_types()` — 参数解析
- `_get_agent_client()` — AgentClient 工厂（lru_cache）
- `prepare()`:
  - 遍历 (fnum, mtype)
  - **为所有类型创建输出目录**（`fdir.mkdir(parents=True, exist_ok=True)`）
  - 调用 `strategy.prepare()`
  - 若返回非 None，写入 prep.json
- `run()`:
  - 遍历 (fnum, mtype)
  - 加载 prep_data 和 qa_data
  - 调用 `strategy.create_evaluator()` 创建每文件 evaluator
  - 调用 `_run_single()` 执行查询级并发
- `_run_single()` — query 级别并发执行：
  1. 跳过已存在且非 failed 的结果（`query_{idx}.json`）
  2. 通过 evaluator.evaluate() 执行评估
  3. 成功时写入结果 JSON（含 source_file, event_index, memory_type）
  4. 失败时写入 fail_record JSON（`{"failed": True, "error": ...}`）
  5. 统计静默失败数

### reporter.py (~80行)

- `collect_results(output_dir: Path) -> tuple[dict[BenchMemoryMode, list[dict]], dict[BenchMemoryMode, int]]` — 从 OUTPUT_DIR 收集 query_*.json，返回 (成功结果, 失败计数)
- `build_report_metrics(all_results: dict[BenchMemoryMode, list[dict]]) -> dict[BenchMemoryMode, dict]` — 构建指标
- `compute_memory_scores(report_data: dict[BenchMemoryMode, dict]) -> None` — 就地计算相对 GOLD 的 memory_score
- `report(output_path: Path | None = None) -> None` — 生成报告 + 打印

## 数据流

### Prepare

```
runner.prepare(file_range, memory_types)
  ├─ parse_file_range() → file_nums
  ├─ _parse_memory_types() → types（验证是否在 STRATEGIES 中）
  ├─ 加载 history_cache（按需：strategies[mode].needs_history()）
  ├─ 解析 agent_client（按需：strategies[mode].needs_agent_for_prep()）
  └─ asyncio.gather(
       对每个 (fnum, mtype):
         ├─ 创建输出目录 file_output_dir(mtype, fnum)
         ├─ strategy.prepare(history_text, output_dir, agent_client?, semaphore)
         └─ 若返回非 None → 写入 prep.json
     )
```

### Run

```
runner.run(file_range, memory_types, reflect_num)
  ├─ 解析参数，获取 agent_client
  ├─ 加载 qa_cache + prep_cache
  └─ asyncio.gather(
       对每个 (fnum, mtype):
         ├─ 加载 prep_data, qa_data（缺失则 skip）
         ├─ strategy.create_evaluator(agent_client, prep_data, ...)
         │   → 每文件初始化（加载 store/构建 search client）
         └─ _run_single(evaluator, events):
              asyncio.gather(
                evaluator.evaluate(task, task_id, gold_memory)
                → 写入 query_{idx}.json（含 skip/fail 逻辑）
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

### 现有测试调整

**`test_common.py`** — import 路径调整为 `strategies.common`

**`test_model_config.py`** — 不变

**`test_runner.py`** — monkeypatch 路径映射：

| 旧路径 | 新路径 |
|-------|--------|
| `vendor_adapter.VehicleMemBench.runner.OUTPUT_DIR` | `vendor_adapter.VehicleMemBench.paths.OUTPUT_DIR` |
| `vendor_adapter.VehicleMemBench.runner._load_qa` | `vendor_adapter.VehicleMemBench.loader.load_qa` |
| `vendor_adapter.VehicleMemBench.runner._evaluate_query` | 对应 strategy 的 `evaluate` 方法 |
| `vendor_adapter.VehicleMemBench.runner._get_agent_client` | `vendor_adapter.VehicleMemBench.runner._get_agent_client`（不变） |
| `vendor_adapter.VehicleMemBench.runner.get_benchmark_config` | `vendor_adapter.VehicleMemBench.model_config.get_benchmark_config`（不变） |

### 新增测试

**`tests/test_vendor_adapter/test_strategies.py`** — 验证每个 Strategy：
- 属性：`mode`、`needs_history()`、`needs_agent_for_prep()`
- `prepare()` 基本行为（mock 掉 vendor 调用）
- `create_evaluator()` 返回的 evaluator 行为正确
- 所有 evaluator 的 evaluate() 必须受 query_semaphore 控制

## 不在范围内

- 不修改 `vendor/` 下的上游代码
- 不修改 `run_benchmark.py` 入口
- 不修改 `model_config.py`
- 不重构 vendor 的 evaluation 函数（process_task_direct 等）
