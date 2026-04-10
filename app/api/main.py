"""FastAPI 应用主入口."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import strawberry
import strawberry.fastapi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from strawberry.scalars import JSON
from strawberry.schema.config import StrawberryConfig

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
    if not Path.exists(WEBUI_DIR):
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


def _ensure_memory_module() -> MemoryModule:
    from app.models.settings import get_chat_model, get_embedding_model  # noqa: PLC0415

    return MemoryModule(
        data_dir=DATA_DIR,
        embedding_model=get_embedding_model(),
        chat_model=get_chat_model(),
    )


_memory_module: MemoryModule | None = None


def get_memory_module() -> MemoryModule:
    """获取或初始化记忆模块单例."""
    global _memory_module
    if _memory_module is None:
        _memory_module = _ensure_memory_module()
    return _memory_module


def _mount_graphql() -> None:
    from app.api.graphql_schema import JSONScalar  # noqa: PLC0415
    from app.api.resolvers.mutation import Mutation as MutationImpl  # noqa: PLC0415
    from app.api.resolvers.query import Query as QueryImpl  # noqa: PLC0415

    schema = strawberry.Schema(
        query=QueryImpl,
        mutation=MutationImpl,
        config=StrawberryConfig(scalar_map={JSON: JSONScalar}),
    )
    graphql_app = strawberry.fastapi.GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")


_mount_graphql()


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
