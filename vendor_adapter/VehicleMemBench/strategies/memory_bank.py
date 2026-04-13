"""记忆库策略：结合嵌入向量和 LLM 的记忆搜索."""

import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.memory.stores.memory_bank import MemoryBankStore
from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.model_config import (
    get_store_chat_model,
    get_store_embedding_model,
)
from vendor_adapter.VehicleMemBench.paths import (
    setup_vehiclemembench_path as _,  # noqa: F401
)
from vendor_adapter.VehicleMemBench.strategies.common import (
    StoreClient,
    format_search_results,
    history_to_interaction_records,
)
from vendor_adapter.VehicleMemBench.strategies.exceptions import (
    VehicleMemBenchError,
)

from evaluation.model_evaluation import (  # isort: skip
    _run_vehicle_task_evaluation,
    get_list_module_tools_schema,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from evaluation.agent_client import AgentClient

logger = logging.getLogger(__name__)

try:
    _SEARCH_TIMEOUT = int(os.environ.get("BENCHMARK_SEARCH_TIMEOUT", str(12 * 3600)))
except ValueError:
    _SEARCH_TIMEOUT = 12 * 3600
    logger.warning(
        "BENCHMARK_SEARCH_TIMEOUT 环境变量值无效，使用默认值 %d",
        _SEARCH_TIMEOUT,
    )

_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION = (
    "You are an intelligent in-car AI assistant responsible for fulfilling user requests by calling the vehicle system API.\n"
    "You have access to a memory store containing user vehicle preferences.\n"
    "- Use memory_search(query, top_k) to look up relevant user preferences\n"
    "- Use list_module_tools(module_name='xxx') to discover available functions\n"
    "- Call the specific functions you need\n"
    "When the available information does not support setting a device to a specific value, "
    "perform only the minimal required action."
)

_CUSTOM_ADAPTER_INITIAL_TOOLS = [
    {"type": "function", "function": get_list_module_tools_schema()},
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search user vehicle preferences by keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def _make_sync_memory_search(
    search_client: StoreClient,
) -> Callable[[str, int], dict[str, Any]]:
    """为同步 vendor 代码创建同步的 memory_search 包装器.

    使用 run_coroutine_threadsafe 将异步搜索调度到主事件循环.
    在主事件循环线程中调用此工厂函数以捕获事件循环引用.
    """
    loop = asyncio.get_running_loop()

    def _search(query: str, top_k: int = 5) -> dict[str, Any]:
        future: Future | None = None
        try:
            future = asyncio.run_coroutine_threadsafe(
                search_client.search(query=query, top_k=top_k),
                loop,
            )
            results = future.result(timeout=_SEARCH_TIMEOUT)
        except TimeoutError:
            if future is not None:
                future.cancel()
            logger.warning("  [warn] memory_search timeout: %r", query)
            return {
                "success": False,
                "error": "search timed out",
                "results": "",
                "count": 0,
            }
        except RuntimeError as e:
            msg = str(e).lower()
            if "event loop" in msg or "closed" in msg:
                logger.warning("  [warn] memory_search: event loop error: %s", e)
                return {"success": False, "error": str(e), "results": "", "count": 0}
            raise
        except OSError as e:
            logger.warning("  [warn] memory_search failed: %s", e)
            return {"success": False, "error": str(e), "results": "", "count": 0}
        except Exception as e:
            logger.exception("  [warn] memory_search unexpected error for %r", query)
            return {"success": False, "error": str(e), "results": "", "count": 0}
        else:
            text, count = format_search_results(results)
            return {"success": True, "results": text, "count": count}

    return _search


class MemoryBankEvaluator:
    """记忆库评估器：使用预构建的搜索客户端."""

    def __init__(
        self,
        agent_client: AgentClient,
        search_client: StoreClient,
        reflect_num: int,
        file_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> None:
        """初始化评估器."""
        self._agent_client = agent_client
        self._reflect_num = reflect_num
        self._file_num = file_num
        self._semaphore = query_semaphore
        self._memory_search = _make_sync_memory_search(search_client)

    async def evaluate(
        self,
        task: dict[str, Any],
        task_id: int,
        gold_memory: str,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """评估单个 query，使用记忆库搜索."""
        memory_funcs = {"memory_search": self._memory_search}
        async with self._semaphore:
            return await asyncio.to_thread(
                _run_vehicle_task_evaluation,
                task=task,
                task_id=task_id,
                agent_client=self._agent_client,
                reflect_num=self._reflect_num,
                system_instruction=_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION,
                request_context=f"{BenchMemoryMode.MEMORY_BANK} file {self._file_num} task {task_id}",
                initial_tools=_CUSTOM_ADAPTER_INITIAL_TOOLS,
                memory_funcs=memory_funcs,
            )


class MemoryBankStrategy:
    """记忆库策略：使用嵌入向量 + LLM 构建可搜索的记忆存储."""

    @property
    def mode(self) -> BenchMemoryMode:
        """返回策略模式."""
        return BenchMemoryMode.MEMORY_BANK

    def needs_history(self) -> bool:
        """是否需要历史文本."""
        return True

    def needs_agent_for_prep(self) -> bool:
        """是否需要 agent client 进行准备."""
        return False

    async def prepare(
        self,
        history_text: str,
        output_dir: Path,
        agent_client: AgentClient | None,  # noqa: ARG002
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        """构建记忆库存储."""
        store_dir = output_dir / "store"
        temp_dir = output_dir / f".store_temp_{uuid.uuid4().hex}"
        async with semaphore:
            temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                chat_model = get_store_chat_model()
                embedding_model = get_store_embedding_model()
                store = MemoryBankStore(
                    data_dir=temp_dir,
                    chat_model=chat_model,
                    embedding_model=embedding_model,
                )
                for record in history_to_interaction_records(history_text):
                    await store.write(record)
                if store_dir.exists():
                    backup_dir = store_dir.with_suffix(f".bak_{temp_dir.name}")
                    await asyncio.to_thread(
                        shutil.move, str(store_dir), str(backup_dir)
                    )
                else:
                    backup_dir = None
                try:
                    await asyncio.to_thread(shutil.move, str(temp_dir), str(store_dir))
                except Exception:
                    if backup_dir is not None:
                        if store_dir.exists():
                            await asyncio.to_thread(shutil.rmtree, store_dir)
                        await asyncio.to_thread(
                            shutil.move, str(backup_dir), str(store_dir)
                        )
                    raise
                if backup_dir is not None and backup_dir.exists():
                    try:
                        await asyncio.to_thread(shutil.rmtree, backup_dir)
                    except OSError as e:
                        logger.warning("清理备份目录失败: %s: %s", backup_dir, e)
            except Exception:
                await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
                raise
        return {"type": BenchMemoryMode.MEMORY_BANK, "data_dir": str(store_dir)}

    async def create_evaluator(
        self,
        agent_client: AgentClient,
        prep_data: dict[str, Any] | None,
        file_num: int,
        reflect_num: int,
        query_semaphore: asyncio.Semaphore,
    ) -> MemoryBankEvaluator:
        """创建记忆库评估器."""
        if prep_data is None:
            msg = f"prep_data 为 None (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.MEMORY_BANK
            )
        data_dir_str = prep_data.get("data_dir")
        if not data_dir_str:
            msg = f"prep_data 缺少 'data_dir' 字段 (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.MEMORY_BANK
            )
        data_dir = Path(data_dir_str)
        exists = await asyncio.to_thread(data_dir.exists)
        if not exists:
            msg = f"记忆库数据目录不存在: {data_dir} (file_num={file_num})"
            raise VehicleMemBenchError(
                msg, file_num=file_num, memory_type=BenchMemoryMode.MEMORY_BANK
            )
        chat_model = get_store_chat_model()
        embedding_model = get_store_embedding_model()
        store = await asyncio.to_thread(
            MemoryBankStore,
            data_dir,
            embedding_model,
            chat_model,
        )
        search_client = StoreClient(store)
        return MemoryBankEvaluator(
            agent_client,
            search_client,
            reflect_num,
            file_num,
            query_semaphore,
        )
