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

from app.api.graphql_schema import JSONScalar
from app.api.resolvers.mutation import Mutation as MutationImpl
from app.api.resolvers.query import Query as QueryImpl
from app.config import DATA_DIR
from app.memory.singleton import _memory_module_state
from app.storage.init_data import init_storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_default_webui = Path(__file__).parent.parent.parent / "webui"
WEBUI_DIR = Path(os.getenv("WEBUI_DIR", _default_webui)).resolve()
if not WEBUI_DIR.exists():
    WEBUI_DIR = _default_webui.resolve()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_storage(DATA_DIR)
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not Path.exists(WEBUI_DIR):
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)
    yield
    mm = _memory_module_state[0]
    if mm is not None:
        await mm.close()
        logger.info("MemoryModule closed")


app = FastAPI(title="知行车秘 - 车载AI智能体", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")


def _mount_graphql() -> None:
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
