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
| 引擎单例 | 模块级缓存（同 embedding） | 参考 `get_cached_embedding_model()` 模式 |
| Protocol 放置 | 独立文件 `app/models/protocol.py` | 避免 `chat.py` ↔ `settings.py` 循环导入 |

## 架构

### 模型层类关系

```
ChatModelProtocol (app/models/protocol.py)
├── ChatModel          — 远程 API（OpenAI SDK）
└── VLLMChatModel      — 本地引擎（vLLM AsyncEngine）
```

`settings.py` 工厂函数 `get_chat_model()` 根据配置中的 `type` 字段选择实例化哪个类。调用方（`workflow.py`、`MemoryModule`）只依赖 `ChatModelProtocol`，无感知具体实现。

### 配置路由

```toml
[model_groups.default]
models = ["local/qwen3.5-2b"]

[model_providers.local]
type = "vllm"
model = "Qwen/Qwen3.5-2B"
tensor_parallel_size = 1
```

- `type = "vllm"` → 创建 `VLLMChatModel`，使用 provider 的 `model` 字段作为 HuggingFace ID（覆盖 model group 解析出的名称）
- 无 `type` 或其他值 → 创建 `ChatModel`（向后兼容）
- model group 配置保持不变（`local/qwen3.5-2b` 仅用于路由到 provider）

### 引擎单例

`get_chat_model()` 使用模块级变量缓存实例（同 `get_cached_embedding_model()` 模式）。vLLM 引擎加载模型耗时数十秒，全局仅初始化一次。

### 可用性检查

`ChatModelProtocol` 增加 `is_available() -> bool` 方法：

- **ChatModel**：尝试连接 provider 的 `base_url/models`，5 秒超时，成功返回 `True`
- **VLLMChatModel**：等待 vLLM 引擎就绪（模型加载完成），返回 `True`；加载失败或超时返回 `False`

测试基础设施使用该方法判断是否跳过 LLM 相关测试。

## 变更清单

### 1. 新建 `app/models/protocol.py`

定义 `ChatModelProtocol`：

```python
class ChatModelProtocol(Protocol):
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: object) -> str: ...
    async def generate_stream(self, prompt: str, system_prompt: str | None = None, **kwargs: object) -> AsyncIterator[str]: ...
    async def batch_generate(self, prompts: list[str], system_prompt: str | None = None) -> list[str]: ...
    def is_available(self) -> bool: ...
```

### 2. 修改 `app/models/chat.py`

- `ChatModel` 添加 `is_available() -> bool` 方法：复用当前 `conftest.py` 中的逻辑（HTTP 请求 `base_url/models`，5 秒超时）
- 移除 Protocol 定义（已提取到 `protocol.py`）
- 导入从 `protocol.py` 获取

### 3. 新建 `app/models/vllm_chat.py`

`VLLMChatModel` 类：

- **构造参数**：`model_id: str`（HuggingFace 模型 ID）、`temperature: float`、`tensor_parallel_size: int = 1`
- **初始化**：创建 `AsyncLLMEngine`（通过 `AsyncEngineArgs`）+ `AutoTokenizer`（用于 `apply_chat_template`）
- **generate(prompt, system_prompt=None) -> str**：
  1. `tokenizer.apply_chat_template()` 构建 prompt
  2. `engine.generate()` 获取完整输出
  3. 返回最终文本
- **generate_stream(prompt, system_prompt=None) -> AsyncIterator[str]**：
  1. 同上构建 prompt
  2. 异步迭代 `engine.generate()` 的输出
  3. yield token 增量
- **batch_generate(prompts, system_prompt=None) -> list[str]**：并发调用 `generate()`
- **is_available() -> bool**：
  - 同步等待 vLLM 引擎就绪（内部使用 `asyncio.run` 或在已运行的事件循环中使用线程桥接）
  - 超时阈值可配置，默认 120 秒（模型加载可能需要较长时间）
  - 返回 `True` 表示引擎已就绪，`False` 表示加载失败或超时

### 4. 修改 `app/models/settings.py`

- `LLMProviderConfig` 增加 `type: str | None = None` 字段
- `get_model_group_providers()` 从 provider 配置中读取 `type` 字段；对 vLLM 类型 provider，`model` 字段使用 provider 配置中的 `model` 值（HuggingFace ID）
- `get_chat_model()` 返回类型改为 `ChatModelProtocol`，根据 `type` 分发：
  - `"vllm"` → `VLLMChatModel`（单例缓存）
  - 其他 → `ChatModel`
- 新增 `_cached_chat_model: ChatModelProtocol | None` 模块级变量实现单例

### 5. 修改 `config/llm.toml`

```toml
[model_providers.local]
type = "vllm"
model = "Qwen/Qwen3.5-2B"
tensor_parallel_size = 1
```

删除 `base_url` 和 `api_key`。

### 6. 修改类型注解引用

- `app/agents/workflow.py`：`chat_model` 类型改为 `ChatModelProtocol`
- `app/memory/memory.py`：`chat_model` 类型改为 `ChatModelProtocol | None`

### 7. 依赖更新 `pyproject.toml`

- 新增 `vllm`
- 新增 `transformers`（显式依赖，用于 `AutoTokenizer`）

### 8. 修改 `tests/conftest.py`

将 `is_llm_available()` 改为调用 `get_chat_model().is_available()`：

```python
@lru_cache(maxsize=1)
def is_llm_available() -> bool:
    try:
        from app.models.settings import get_chat_model
        model = get_chat_model()
        return model.is_available()
    except Exception:
        return False
```

`SKIP_IF_NO_LLM` 保持不变（仍基于 `is_llm_available()`）。

对 `VLLMChatModel`，`is_available()` 会等待模型加载完成（最长 120 秒），因此测试在 GPU 环境下会正常执行，在无 GPU 环境下会因异常返回 `False` 而被跳过。

### 9. 适配现有测试

- `tests/test_chat.py`：`ChatModel()` 直接构造改为通过 `get_chat_model()` 获取实例；类型注解改用 `ChatModelProtocol`
- `tests/test_api.py`：无改动（通过 `SKIP_IF_NO_LLM` 自动适配）
- `tests/test_memory_bank.py`：`TestMemoryModuleIntegration` 中的 `MemoryModule(tmp_path)` 无需改动（自动通过工厂获取模型）
- 其他使用 `mock_chat_model` fixture 的测试无需改动（mock 对象满足 Protocol 的 generate 方法即可）

## 未解决的问题

- Qwen3.5-2B 的 `enable_thinking` 参数是否需要暴露到配置中（该模型支持思考模式）
