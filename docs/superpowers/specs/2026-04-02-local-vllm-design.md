# 本地 vLLM 引擎集成设计

## 目标

将本地 LLM（Qwen3.5-2B）通过内嵌 vLLM AsyncEngine 集成到项目中，作为默认模型配置，替代外部 vLLM 服务器依赖。

## 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 集成方式 | 内嵌 vLLM AsyncEngine | 无需单独管理服务器进程 |
| 模型加载 | HuggingFace 自动下载 | 首次运行自动获取，后续使用缓存 |
| 流式输出 | 支持 | 保留现有流式能力 |
| GPU 不可用时 | 报错退出 | 不做 CPU fallback |
| 架构方案 | 新建 VLLMChatModel 类 | 与 ChatModel 并存，关注点分离 |

## 架构

### 模型层类关系

```
ChatModelProtocol (Protocol)
├── ChatModel          — 远程 API（OpenAI SDK）
└── VLLMChatModel      — 本地引擎（vLLM AsyncEngine）
```

`settings.py` 工厂函数 `get_chat_model()` 根据配置中的 `type` 字段选择实例化哪个类。调用方（`workflow.py`、`MemoryModule`）只依赖 `ChatModelProtocol`，无感知具体实现。

### 配置路由

```toml
[model_providers.local]
type = "vllm"
model = "Qwen/Qwen3.5-2B"
tensor_parallel_size = 1
```

- `type = "vllm"` → 创建 `VLLMChatModel`
- 无 `type` 或其他值 → 创建 `ChatModel`（向后兼容）

## 变更清单

### 1. 新建 `app/models/vllm_chat.py`

`VLLMChatModel` 类：

- **构造参数**：`model_id: str`（HuggingFace 模型 ID）、`temperature: float`、`tensor_parallel_size: int = 1`
- **初始化**：创建 `AsyncLLMEngine` + `AutoTokenizer`
- **generate(prompt, system_prompt=None) -> str**：
  1. `tokenizer.apply_chat_template()` 构建 prompt
  2. `engine.generate()` 获取完整输出
  3. 返回最终文本
- **generate_stream(prompt, system_prompt=None) -> AsyncIterator[str]**：
  1. 同上构建 prompt
  2. 异步迭代 `engine.generate()` 的输出
  3. yield token 增量
- **batch_generate(prompts, system_prompt=None) -> list[str]**：并发调用 `generate()`

### 2. 修改 `app/models/chat.py`

添加 `ChatModelProtocol` 定义：

```python
class ChatModelProtocol(Protocol):
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: object) -> str: ...
    async def generate_stream(self, prompt: str, system_prompt: str | None = None, **kwargs: object) -> AsyncIterator[str]: ...
    async def batch_generate(self, prompts: list[str], system_prompt: str | None = None) -> list[str]: ...
```

`ChatModel` 类本身不做改动。

### 3. 修改 `app/models/settings.py`

- `LLMProviderConfig` 增加 `type: str | None = None` 字段
- `get_model_group_providers()` 从 provider 配置中读取 `type` 字段
- `get_chat_model()` 返回类型改为 `ChatModelProtocol`，根据 `type` 分发：
  - `"vllm"` → `VLLMChatModel`
  - 其他 → `ChatModel`
- `get_chat_model()` 返回类型注解更新

### 4. 修改 `config/llm.toml`

```toml
[model_providers.local]
type = "vllm"
model = "Qwen/Qwen3.5-2B"
tensor_parallel_size = 1
```

删除 `base_url` 和 `api_key`。

### 5. 修改类型注解引用

- `app/agents/workflow.py`：`chat_model` 类型改为 `ChatModelProtocol`
- `app/memory/memory.py`：`chat_model` 类型改为 `ChatModelProtocol | None`

### 6. 依赖更新 `pyproject.toml`

- 新增 `vllm`
- 新增 `transformers`（显式依赖，用于 `AutoTokenizer`）

## 未解决的问题

- vLLM 引擎实例应在整个应用生命周期内复用（单例）。当前设计通过 `get_chat_model()` 每次创建新实例，需要加入缓存机制。
- Qwen3.5-2B 的 `enable_thinking` 参数是否需要暴露到配置中（该模型支持思考模式）。
