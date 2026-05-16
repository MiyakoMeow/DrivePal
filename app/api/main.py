"""FastAPI 应用主入口."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.conversation import _conversation_manager
from app.api.errors import AppError, app_error_handler, validation_error_handler
from app.api.middleware import UserIdentityMiddleware
from app.api.scheduler_registry import get_or_create_scheduler, stop_all_schedulers
from app.api.v1.data import router as data_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.presets import router as presets_router
from app.api.v1.query import router as query_router
from app.api.v1.reminders import router as reminders_router
from app.api.v1.scheduler import router as scheduler_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.voice import router as voice_router
from app.api.v1.ws import router as ws_router
from app.config import DATA_DIR
from app.models.chat import close_client_cache
from app.models.embedding import aclose_embedding_model_cache
from app.storage.init_data import init_storage
from app.voice import VoiceService

logger = logging.getLogger(__name__)

_default_webui = Path(__file__).parent.parent.parent / "webui"
WEBUI_DIR = Path(os.getenv("WEBUI_DIR", _default_webui)).resolve()
if not WEBUI_DIR.exists():
    WEBUI_DIR = _default_webui.resolve()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_storage()
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not Path.exists(WEBUI_DIR):
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)

    async def _periodic_cleanup() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                _conversation_manager.cleanup_expired()
            except Exception:
                logger.exception("Periodic conversation cleanup failed")

    cleanup_task = asyncio.create_task(_periodic_cleanup())

    from app.memory.singleton import close_memory_module

    sched = await get_or_create_scheduler("default")
    logger.info("ProactiveScheduler started for default user")

    # --- 语音流水线 ---
    voice_service = VoiceService()
    app.state.voice_service = voice_service

    if sched is not None:
        await voice_service.start(sched)

    yield
    await voice_service.stop()
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    await stop_all_schedulers()
    await close_memory_module()
    logger.info("MemoryModule closed")
    await aclose_embedding_model_cache()
    logger.info("Embedding model cache cleared")
    await close_client_cache()
    logger.info("Chat client cache closed")


app = FastAPI(title="知行车秘 - 车载AI智能体", lifespan=_lifespan)


def _build_cors_config() -> dict:
    # 从环境变量动态配置 CORS origins，不同部署环境可调整而无需改代码
    origins_str = os.getenv("DRIVEPAL_CORS_ORIGINS", "*")
    origins = [o.strip() for o in origins_str.split(",") if o.strip()]
    # 空值回退通配符，避免 allow_origins=[] 阻断所有跨域请求
    if not origins:
        origins = ["*"]
    is_wildcard = origins == ["*"]
    # CORS 规范：通配符 origin 不应携带 credentials，浏览器会拒绝
    return {
        "allow_origins": origins,
        "allow_credentials": not is_wildcard,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


app.add_middleware(CORSMiddleware, **_build_cors_config())
app.add_middleware(UserIdentityMiddleware)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")

# v1 API 路由
API_V1 = APIRouter(prefix="/api/v1")
API_V1.include_router(query_router, prefix="/query", tags=["query"])
API_V1.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
API_V1.include_router(presets_router, prefix="/presets", tags=["presets"])
API_V1.include_router(data_router, tags=["data"])
API_V1.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
API_V1.include_router(reminders_router, prefix="/reminders", tags=["reminders"])
API_V1.include_router(voice_router, prefix="/voice", tags=["voice"])
API_V1.include_router(ws_router, prefix="/ws", tags=["ws"])
API_V1.include_router(scheduler_router, prefix="/scheduler", tags=["scheduler"])
app.include_router(API_V1)


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
