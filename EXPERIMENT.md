# 对比实验

基于 [VehicleMemBench](https://github.com/isyuhaochen/VehicleMemBench) 的车载记忆基准评估框架。

## 系统架构

```mermaid
flowchart TD
    CLI[run_benchmark.py<br>CLI 入口，分发命令]
    Runner[adapters/runner.py<br>VehicleMemBench 评估运行器]
    Adapters[adapters/memory_adapters<br>记忆存储适配器]
    Stores[app/memory/stores<br>原生记忆存储后端实现]
    
    CLI --> Runner
    Runner --> Adapters
    Adapters --> Stores
    
    subgraph Adapters
        M[memory_bank]
    end
```

## 适配器模式

`adapters/memory_adapters/` 通过统一接口封装 `app/memory/stores/`，使 VehicleMemBench 能以适配器方式调用（当前仅支持 MemoryBank）：

| 适配器 | 封装 | 原理 |
|--------|------|------|
| `MemoryBankAdapter` | `MemoryBankStore` | 遗忘曲线 + 分层记忆（唯一支持） |

## 运行基准测试

```bash
# 全流程
uv run python run_benchmark.py all --file-range 1-50

# 分阶段运行
uv run python run_benchmark.py prepare --file-range 1-50
uv run python run_benchmark.py run --file-range 1-50

# 生成报告
uv run python run_benchmark.py report
```

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--file-range` | `1-50` | 评估文件范围（如 `1-10` 或 `1,3,5`） |
| `--memory-types` | `gold,summary,kv,memory_bank` | 记忆类型 |

## 基准测试数据结构

```text
data/benchmark/
├── qa_{n}.json           # QA 测试用例
├── history_{n}.txt       # 历史交互记录
└── results/              # 运行结果
    └── {memory_type}/
        └── ...
```

## VehicleMemBench 子模块

作为 `vendor/VehicleMemBench` 子模块引入，评估逻辑由供应商提供。

## 实验报告 API

##### GET `/api/experiment/report` - 获取实验报告
