"""独立语音 FastAPI 服务。不依赖 scheduler/memory/workflow。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.voice import router as voice_router
from app.voice import VoiceService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_WEBUI_DIR = Path(__file__).parent.parent.parent / "webui"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    voice_service = VoiceService()
    _app.state.voice_service = voice_service
    ok = await voice_service.start()
    if not ok:
        logger.warning(
            "Voice service unavailable (ASR/pyaudio missing, or disabled), continuing without audio"
        )
    yield
    await voice_service.stop()


app = FastAPI(title="知行车秘 — 语音服务", lifespan=_lifespan)

app.include_router(voice_router, prefix="/api/v1/voice")

if _WEBUI_DIR.exists():
    app.mount("/static", StaticFiles(directory=_WEBUI_DIR), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        """根路径返回 WebUI。"""
        return FileResponse(_WEBUI_DIR / "index.html")


def serve(host: str = "127.0.0.1", port: int = 34568) -> None:
    """启动独立语音服务。"""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    serve()
