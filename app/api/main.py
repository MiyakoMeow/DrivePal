"""FastAPI 应用主入口."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
import strawberry
import strawberry.fastapi

from app.memory.memory import MemoryModule
from app.storage.init_data import init_storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="知行车秘 - 车载AI智能体")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
WEBUI_DIR = Path(os.getenv("WEBUI_DIR", Path(__file__).parent.parent.parent / "webui"))


@app.on_event("startup")
async def _startup() -> None:
    init_storage(DATA_DIR)
    logger.info("Data directory initialized: %s", DATA_DIR)


def _ensure_memory_module() -> MemoryModule:
    from app.models.settings import get_chat_model, get_embedding_model

    return MemoryModule(
        data_dir=DATA_DIR,
        embedding_model=get_embedding_model(),
        chat_model=get_chat_model(),
    )


_memory_module: MemoryModule | None = None


def get_memory_module() -> MemoryModule:
    global _memory_module
    if _memory_module is None:
        _memory_module = _ensure_memory_module()
    return _memory_module


def _mount_graphql() -> None:
    from app.api.resolvers.mutation import Mutation as MutationImpl
    from app.api.resolvers.query import Query as QueryImpl

    schema = strawberry.Schema(query=QueryImpl, mutation=MutationImpl)
    graphql_app = strawberry.fastapi.GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")


_mount_graphql()

webui_path = WEBUI_DIR


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(webui_path / "index.html")
