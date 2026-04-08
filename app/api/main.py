"""FastAPI 应用主入口."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import strawberry
import strawberry.fastapi

from app.memory.memory import MemoryModule
from app.storage.init_data import init_storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

_default_webui = Path(__file__).parent.parent.parent / "webui"
WEBUI_DIR = Path(os.getenv("WEBUI_DIR", _default_webui)).resolve()
if not WEBUI_DIR.exists():
    WEBUI_DIR = _default_webui.resolve()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_storage(DATA_DIR)
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not WEBUI_DIR.exists():
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)
    yield


app = FastAPI(title="知行车秘 - 车载AI智能体", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")

_memory_module: MemoryModule | None = None


def _get_memory_module() -> MemoryModule:
    global _memory_module
    if _memory_module is None:
        from app.models.settings import get_chat_model, get_embedding_model

        _memory_module = MemoryModule(
            data_dir=DATA_DIR,
            embedding_model=get_embedding_model(),
            chat_model=get_chat_model(),
        )
    return _memory_module


def reset_memory_module() -> None:
    """重置记忆模块单例（仅用于测试隔离）."""
    global _memory_module
    _memory_module = None


async def _graphql_context(request: Request) -> dict[str, Any]:
    return {"memory_module": _get_memory_module(), "data_dir": DATA_DIR}


def _mount_graphql() -> None:
    from strawberry.scalars import JSON
    from strawberry.schema.config import StrawberryConfig

    from app.api.graphql_schema import JSONScalar
    from app.api.resolvers.mutation import Mutation as MutationImpl
    from app.api.resolvers.query import Query as QueryImpl

    schema = strawberry.Schema(
        query=QueryImpl,
        mutation=MutationImpl,
        config=StrawberryConfig(scalar_map={JSON: JSONScalar}),
    )
    graphql_app = strawberry.fastapi.GraphQLRouter(
        schema, context_getter=_graphql_context
    )
    app.include_router(graphql_app, prefix="/graphql")


_mount_graphql()


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
