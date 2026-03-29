# VehicleMemBench 集成设计

## 目标

用 VehicleMemBench 替换现有实验系统，评测自研 4 种记忆后端在车载多用户长期记忆场景下的表现。

## 方案

**方案 B：Git 子模块 + 适配层**。VehicleMemBench 作为 `vendor/VehicleMemBench` 子模块引入，**禁止修改其任何文件**。通过 `adapters/` 适配层桥接自研记忆后端。

**评测管线策略**：`adapters/runner.py` 自写评测管线，直接调用 VehicleMemBench 的底层模块（`environment/`、`evaluation/eval_utils.py`、`evaluation/model_evaluation.py`），绕过 `memorysystem_evaluation.py` 的注册机制。具体而言：
- summary/kv/gold 基线 → 调用 `model_evaluation.py` 的 `model_evaluation()` 函数
- 自研 4 种后端 → runner.py 自行编排 add + test 流程，复用 VehicleMemBench 的 `VehicleWorld`、`calculate_turn_result()`、`score_tool_calls()` 等

## 删除范围

- `app/experiment/` 整个目录
- `run_experiment.py`
- `config/evaluation_config.json`
- `data/` 中旧实验输出
- `tests/` 中旧实验相关测试（test_evaluate.py, test_execute.py, test_judge.py, test_prepare.py, test_experiment_runner.py, test_e2e_pipeline.py）

保留：`app/memory/`, `app/agents/`, `app/models/`, `app/storage/`, `app/api/`, `webui/`, `main.py`。

## 项目结构

```
thesis-cockpit-memo/
├── vendor/
│   └── VehicleMemBench/            # git submodule (禁止修改)
│       ├── benchmark/              # qa_data/ + history/
│       ├── environment/            # VehicleWorld 仿真
│       └── evaluation/             # 评测管线
│           └── memorysystems/
│               └── __init__.py     # 最小修改：注册自研适配器
│
├── adapters/                        # 适配层
│   ├── __init__.py
│   ├── model_config.py             # 模型配置桥接
│   ├── memory_adapters/            # 自研后端适配器
│   │   ├── __init__.py             # 注册表
│   │   ├── common.py               # 共享工具
│   │   ├── keyword_adapter.py
│   │   ├── llm_only_adapter.py
│   │   ├── embeddings_adapter.py
│   │   └── memory_bank_adapter.py
│   └── runner.py                   # 实验运行器
│
├── run_benchmark.py                # 新 CLI 入口
├── config/llm.json                 # 扩展配置
├── app/                            # 保留（实际系统）
├── main.py                         # 保留
└── tests/test_adapters/            # 新增测试
```

## 模型配置

### config/llm.json

```json
{
  "llm": [
    {
      "model": "qwen3.5-2b",
      "base_url": "http://127.0.0.1:50721/v1",
      "api_key": "none",
      "temperature": 0.7
    }
  ],
  "benchmark": {
    "model": "MiniMax-M2.7",
    "base_url": "https://api.minimaxi.com/v1",
    "api_key_env": "MINIMAX_API_KEY",
    "temperature": 0.0,
    "max_tokens": 8192
  },
  "embedding": [
    {
      "model": "BAAI/bge-small-zh-v1.5",
      "device": "cpu"
    }
  ]
}
```

- `llm` — 本地 qwen3.5-2b，用于所有评测环节（记忆构建 + 在线执行）
- `benchmark` — MiniMax-M2.7 备选配置。缺失时 `get_benchmark_client()` 回退到 `llm` 配置
- `embedding` — 本地 BGE，用于 embeddings/memory_bank 后端
- 所有聊天模型仅支持 OpenAI 兼容接口

### adapters/model_config.py

提供以下函数：

- `get_benchmark_client()` → `openai.OpenAI` 实例。优先读取 `benchmark` 节，缺失则回退到 `llm[0]`。从 `api_key_env` 环境变量读取 API key
- `get_store_chat_model()` → `ChatModel` 实例。供自研记忆后端构造使用（从 `llm` 配置构造）
- `get_store_embedding_model()` → `EmbeddingModel` 实例。供 embeddings/memory_bank 后端构造使用（从 `embedding` 配置构造）

## 评测模型使用

**全部统一使用本地 qwen3.5-2b + BGE**：

| 环节 | 模型 |
|------|------|
| Summary 基线记忆构建 | 本地 qwen3.5-2b |
| KV Store 基线记忆构建 | 本地 qwen3.5-2b |
| 自研后端记忆构建 | 本地 qwen3.5-2b + BGE |
| 所有模式的在线执行（Agent 骨干） | 本地 qwen3.5-2b |

端侧部署验证：全部走本地模型，模拟真实端侧条件。

## 记忆适配器

### 模块接口

每个适配器是一个类（如 `KeywordAdapter`），不依赖 VehicleMemBench 的 memorysystem 注册机制。接口如下：

| 导出 | 类型 | 说明 |
|------|------|------|
| `TAG` | `str` | 模块标识，如 `"keyword"` |
| `add(history_text: str) -> dict` | 方法 | 将 history 文本注入自研记忆系统，返回序列化状态 |
| `init_state() -> dict` | 方法 | 初始化适配器状态 |
| `close_state(state)` | 方法 | 清理 |
| `get_search_client(state) -> StoreClient` | 方法 | 返回检索客户端 |

`StoreClient` 提供统一的 `search(query, top_k=5) -> list[SearchResult]` 接口。不需要 `user_id` 参数（每个适配器实例对应一个 persona group）。

### 并发策略

runner.py 编排评测时决定并发：

| 适配器 | 是否可并行 | 原因 |
|--------|-----------|------|
| keyword | 是 | JSON 文件读写，无并发冲突 |
| llm_only | 是 | 无共享状态 |
| embeddings | 是 | 向量索引只读，无冲突 |
| memory_bank | 否 | 遗忘曲线/强化状态有副作用 |

### 检索客户端

每个适配器的 `get_search_client()` 返回 `StoreClient` 对象：

```python
class StoreClient:
    def __init__(self, store: MemoryStore):
        self.store = store

    def search(self, query, top_k=5):
        return self.store.search(query=query, top_k=top_k)  # list[SearchResult]
```

### 检索结果格式化

runner.py 统一处理，不依赖适配器导出：

```python
def format_search_results(results: list[SearchResult]) -> tuple[str, int]:
    texts = [r.event.content for r in results if r.event]
    return ("\n".join(texts), len(texts))
```

### 四种适配器

| 后端 | add 阶段 | test 阶段检索 |
|------|----------|--------------|
| keyword | 对话→InteractionRecord→EventStorage | KeywordSearch 关键词匹配 |
| llm_only | 同上 | LLM 逐条语义判断 |
| embeddings | 同上 + BGE 向量化 | 向量余弦相似度(0.4) + keyword fallback |
| memory_bank | 同上 + 遗忘曲线/聚合/分层摘要 | 混合检索 + 记忆强化 + 关联展开 |

### common.py

- `history_to_interaction_records(history_text) -> list[MemoryEvent]` — 数据转换：
  - 按行解析 history_N.txt（格式：`[YYYY-MM-DD HH:MM] Speaker: Content`）
  - 每行转为一个 `MemoryEvent`，字段映射：
    - `id`: 自增
    - `content`: 行内容（`Speaker: Content`）
    - `description`: 同 content
    - `type`: 根据关键词推断（schedule_check/event_add/event_delete/general），默认 `general`
    - `date_group`: 从时间戳提取 `YYYY-MM-DD`
    - `strength`: 默认 1.0
- `format_search_results(results: list[SearchResult]) -> (str, int)` — 见上方实现

### 注册表

`adapters/memory_adapters/__init__.py`：

```python
ADAPTERS = {
    "keyword": KeywordAdapter,
    "llm_only": LLMOnlyAdapter,
    "embeddings": EmbeddingsAdapter,
    "memory_bank": MemoryBankAdapter,
}
```

不修改 VehicleMemBench 的 `memorysystems/__init__.py`。runner.py 直接从本注册表获取适配器。

## 实验运行器

### run_benchmark.py CLI

```
python run_benchmark.py prepare [--file-range 1-50] [--memory-types keyword,llm_only,embeddings,memory_bank,summary,kv,gold]
python run_benchmark.py run     [--file-range 1-50] [--memory-types ...]
python run_benchmark.py report  [--output report.json]
python run_benchmark.py all     [--file-range 1-50] [--memory-types ...]
```

args Namespace 必须包含的属性（由 `argparse` 构造）：

| 属性 | 说明 |
|------|------|
| `file_range` | 文件范围字符串如 `"1-50"` |
| `max_workers` | 并行 worker 数 |
| `output_dir` | 输出目录（`data/benchmark/`） |
| `memory_types` | 要评测的后端列表 |

history/qa 目录路径硬编码为 `vendor/VehicleMemBench/benchmark/`。模型实例通过 `model_config.py` 获取。

### 三阶段 Pipeline

| 阶段 | 功能 |
|------|------|
| prepare | 基线（summary/kv/gold）：直接调用 VehicleMemBench 的 `model_evaluation.py`。自研后端：通过适配器 `add()` 构建记忆，序列化到 `data/benchmark/`。支持断点续跑 |
| run | 基线：由 `model_evaluation.py` 完成。自研后端：runner.py 编排工具调用循环，复用 VehicleMemBench 的 `VehicleWorld` + `_run_vehicle_task_evaluation()` 逻辑（直接 import），用 MiniMax 作为 Agent 骨干。支持断点续跑 |
| report | 汇总所有结果，调用 VehicleMemBench 的 `calculate_turn_result()` + `_build_metric()` 计算指标，按 reasoning_type 分组 |

### 评测模式

| 模式 | 记忆来源 | 说明 |
|------|---------|------|
| gold | qa 文件的 gold_memory 字段 | 理论上限 |
| summary | VehicleMemBench 原生递归摘要 | 基线 |
| kv | VehicleMemBench 原生 KV Store | 基线 |
| keyword | 自研 keyword 后端 | 自研 |
| llm_only | 自研 llm_only 后端 | 自研 |
| embeddings | 自研 embeddings 后端 | 自研 |
| memory_bank | 自研 memory_bank 后端 | 自研 |

### 输出指标

使用 VehicleMemBench 实际指标名：

| 指标名 | 别名（论文） | 说明 |
|--------|-------------|------|
| `exact_match_rate` | ESM | Overall + 按 reasoning_type 分组 |
| `state_f1_positive` | F-F1 | Field-level F1 |
| `state_f1_change` | V-F1 | Value-level F1 |
| `change_accuracy` | — | Value-level accuracy |
| `avg_pred_calls` | Calls | 平均工具调用次数 |
| MemoryScore | MemoryScore | = exact_match_rate_auto / exact_match_rate_gold（在 report 阶段计算） |

## 测试策略

- **单元测试**：`history_to_interaction_records` 数据转换、`format_search_results` 格式化、`StoreClient` 接口
- **集成测试**：单个 history 文件 → 适配器 add → search 端到端（使用小规模 fixture 数据）
- **契约测试**：验证每个适配器类实现了所有必需方法

## 未解决问题

1. 本地 qwen3.5-2b 的上下文窗口是否能处理 VehicleMemBench 的工具调用循环？如果不够，可能需要截断策略。
2. Summary 基线用 2B 模型做递归摘要的质量可能显著低于论文中用强模型的结果，论文中需说明是端侧条件限制。
3. runner.py 直接 import VehicleMemBench 的内部函数（如 `_run_vehicle_task_evaluation`），这些函数以 `_` 开头表示模块私有，需确认 import 后的行为是否稳定。如有必要可复制关键函数到 adapters/ 中。
