"""FastAPI 应用主入口."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.scheduler import ProactiveScheduler

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.conversation import _conversation_manager
from app.api.errors import AppError, app_error_handler, validation_error_handler
from app.api.middleware import UserIdentityMiddleware
from app.api.v1.data import router as data_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.presets import router as presets_router
from app.api.v1.query import router as query_router
from app.api.v1.reminders import router as reminders_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.voice import router as voice_router
from app.api.v1.ws import router as ws_router
from app.config import DATA_DIR
from app.models.chat import close_client_cache
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

    # 主动调度器
    from app.agents.workflow import AgentWorkflow
    from app.api.v1.ws_manager import ws_manager as ws_mgr
    from app.memory.singleton import close_memory_module, get_memory_module
    from app.scheduler import ProactiveScheduler

    _schedulers: dict[str, ProactiveScheduler] = {}

    async def _init_scheduler(user_id: str) -> ProactiveScheduler:
        wf = AgentWorkflow(current_user=user_id)
        mm = get_memory_module()
        sched = ProactiveScheduler(
            workflow=wf,
            memory_module=mm,
            user_id=user_id,
            ws_manager=ws_mgr,
        )
        await sched.start()
        _schedulers[user_id] = sched
        return sched

    try:
        sched = await _init_scheduler("default")
        logger.info("ProactiveScheduler started for default user")
    except Exception as e:
        logger.warning("Failed to start scheduler: %s", e)
        sched = None

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
    for uid, sched in _schedulers.items():
        await sched.stop()
        logger.info("Scheduler stopped for %s", uid)
    await close_memory_module()
    logger.info("MemoryModule closed")
    await close_client_cache()
    logger.info("Chat client cache closed")


app = FastAPI(title="知行车秘 - 车载AI智能体", lifespan=_lifespan)
# CORS：开发用，部署前须收敛 origin 列表
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
app.include_router(API_V1)


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
