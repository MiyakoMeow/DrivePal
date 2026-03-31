# 移除 LangChain 生态：改用 openai SDK + 手写管道

## 背景

项目当前依赖 LangChain 生态 5 个包（langchain-core, langchain-openai, langchain-huggingface, langgraph, langchain-community），但实际使用深度极浅：

- **ChatModel**：仅用 `ChatOpenAI.invoke()` + 手工拼消息，未用 chain/agent/template 等高级抽象
- **EmbeddingModel**：仅用 `embed_query()` / `embed_documents()`
- **工作流**：仅线性流水线（4 节点顺序执行），无需图引擎
- **langchain-community**：从未导入，死依赖

目标：完全脱离 LangChain 生态，用 `openai` SDK + `sentence-transformers` + 手写管道替代。

## 变更范围

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `pyproject.toml` | 修改 | 移除 5 个 langchain 包，新增 `openai` |
| `app/models/chat.py` | 重写 | `ChatOpenAI` → `openai.OpenAI` |
| `app/models/embedding.py` | 重写 | LangChain 封装 → 原生 SDK 调用 |
| `app/agents/state.py` | 修改 | `BaseMessage` → `dict` 消息格式 |
| `app/agents/workflow.py` | 重写 | `StateGraph` → 简单 `Pipeline` |
| `tests/test_chat.py` | 修改 | 适配新消息格式 |

## 详细设计

### 1. ChatModel（`app/models/chat.py`）

**替代方案**：`openai.OpenAI` 直接调用

```python
import openai

class ChatModel:
    def __init__(self, providers, temperature=None): ...  # 不变

    def _create_client(self, provider: LLMProviderConfig) -> openai.OpenAI:
        kwargs = {"api_key": provider.provider.api_key or "not-needed"}
        if provider.provider.base_url:
            kwargs["base_url"] = provider.provider.base_url
        return openai.OpenAI(**kwargs)

    def generate(self, prompt, system_prompt=None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        # fallback 循环不变
        for provider in self.providers:
            client = self._create_client(provider)
            resp = client.chat.completions.create(
                model=provider.provider.model,
                messages=messages,
                temperature=...,
            )
            return resp.choices[0].message.content
        raise RuntimeError(...)

    async def generate_stream(self, prompt, system_prompt=None) -> AsyncIterator[str]:
        # 同 generate 但用 stream=True + async client
        client = openai.AsyncOpenAI(...)
        stream = await client.chat.completions.create(..., stream=True)
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
```

关键点：
- 移除 `HumanMessage`, `SystemMessage`, `RunnableConfig`, `SecretStr` 全部导入
- `api_key` 为 None 时传 `"not-needed"`（兼容本地模型如 Ollama）
- 对外接口 `generate()` 签名不变
- 新增 `generate_stream()` 支持流式

### 2. EmbeddingModel（`app/models/embedding.py`）

**替代方案**：
- OpenAI 兼容端：`openai.OpenAI().embeddings.create()`
- HuggingFace 本地端：`sentence_transformers.SentenceTransformer`（已是依赖）

```python
from sentence_transformers import SentenceTransformer

class EmbeddingModel:
    def _create_openai_client(self, provider) -> openai.OpenAI:
        # 同 ChatModel 的客户端创建
        ...

    def _create_local_client(self, provider) -> SentenceTransformer:
        return SentenceTransformer(
            provider.provider.model,
            device=provider.device,
        )

    def encode(self, text: str) -> list[float]:
        provider = self.providers[0]  # fallback 逻辑保留
        if provider.provider.base_url:
            resp = self._create_openai_client(provider).embeddings.create(
                model=provider.provider.model,
                input=text,
            )
            return resp.data[0].embedding
        model = self._create_local_client(provider)
        return model.encode(text, normalize_embeddings=True).tolist()

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        # 同理，openai 批量 input=texts / sentence-transformers encode 批量
        ...
```

关键点：
- 移除 `HuggingFaceEmbeddings`, `OpenAIEmbeddings`, `SecretStr` 全部导入
- 缓存机制保留（`_EMBEDDING_MODEL_CACHE`）
- fallback 逻辑保留
- `encode()` / `batch_encode()` 签名不变

### 3. AgentState（`app/agents/state.py`）

```python
class AgentState(TypedDict):
    messages: list[dict]          # {"role": "user", "content": "..."}
    context: dict
    task: Optional[dict]
    decision: Optional[dict]
    memory_mode: "MemoryMode"
    result: Optional[str]
    event_id: Optional[str]
```

关键点：
- `messages: list[BaseMessage]` → `messages: list[dict]`
- 移除 `langchain_core.messages` 导入

### 4. AgentWorkflow（`app/agents/workflow.py`）

**替代方案**：简单 `Pipeline` 类，顺序执行 4 个节点函数

```python
class AgentWorkflow:
    def __init__(self, ...): ...  # 不变

    def _build_pipeline(self) -> None:
        self._nodes = [
            ("context_agent", self._context_node),
            ("task_agent", self._task_node),
            ("strategy_agent", self._strategy_node),
            ("execution_agent", self._execution_node),
        ]

    def run(self, user_input: str) -> tuple[str, Optional[str]]:
        state: AgentState = {
            "messages": [{"role": "user", "content": user_input}],
            ...
        }
        for name, node_fn in self._nodes:
            updates = node_fn(state)
            state.update(updates)
        return state.get("result") or "处理完成", state.get("event_id")
```

各节点内部变更：
- `messages[-1].content` → `messages[-1]["content"]`
- `HumanMessage(content=...)` → `{"role": "user", "content": ...}`
- 其余逻辑不变

移除的导入：`StateGraph`, `END`, `CompiledStateGraph`, `HumanMessage`

### 5. 测试适配（`tests/test_chat.py`）

```python
# from langchain_core.messages import HumanMessage  ← 移除
state: AgentState = {
    "messages": [{"role": "user", "content": "查一下会议"}],
    ...
}
```

### 6. 依赖变更（`pyproject.toml`）

**移除**：
- `langchain-core`
- `langchain-openai`
- `langchain-huggingface`
- `langgraph`
- `langchain-community`

**新增**：
- `openai`（已通过 langchain-openai 间接安装，现在显式声明）

**保留**：
- `sentence-transformers`（已存在，用于本地 embedding）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| openai SDK 的 embedding 响应格式可能与 LangChain 封装不同 | 统一返回 `list[float]`，上层无感知 |
| 流式接口是新增 API，需确保下游集成正确 | 暂不暴露到 workflow.run()，仅在 ChatModel 层提供 |
| HuggingFace 本地模型加载方式变化（SentenceTransformer vs HuggingFaceEmbeddings） | 同模型名兼容；缓存机制保留避免重复加载 |

## 不变的部分

- `app/models/settings.py` — 纯配置，不依赖 LangChain，无需改动
- `app/memory/` — 不直接导入 LangChain，无需改动
- `app/agents/prompts.py` — 纯字符串，无需改动
- `app/storage/` — 纯 JSON 存储，无需改动
- `app/` 下的 API 路由、服务层 — 通过 ChatModel/workflow 间接使用，接口不变
