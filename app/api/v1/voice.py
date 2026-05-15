"""语音模块 REST 路由。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.voice.config import VoiceConfig

if TYPE_CHECKING:
    from app.voice.service import VoiceService

_NOT_INIT = "VoiceService not initialized"

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


def _get_svc(request: Request) -> VoiceService:
    svc: VoiceService | None = getattr(request.app.state, "voice_service", None)
    if svc is None:
        raise RuntimeError(_NOT_INIT)
    return svc


@router.get("/status")
async def voice_status(request: Request) -> dict:
    """当前语音运行状态。"""
    return _get_svc(request).status


@router.post("/start")
async def voice_start(request: Request) -> JSONResponse:
    """开启语音流水线。"""
    svc = _get_svc(request)
    if svc.status["running"]:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "ALREADY_RUNNING",
                    "message": "Voice is already running",
                }
            },
        )
    ok = await svc.start()
    if not ok:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VOICE_DISABLED",
                    "message": "Voice is disabled in config",
                }
            },
        )
    return JSONResponse(content={"status": "started"})


@router.post("/stop")
async def voice_stop(request: Request) -> dict:
    """停止语音流水线。"""
    await _get_svc(request).stop()
    return {"status": "stopped"}


@router.get("/config")
async def voice_config_get() -> dict:
    """当前配置。"""
    cfg = VoiceConfig.load()
    return {
        "enabled": cfg.enabled,
        "device_index": cfg.device_index,
        "sample_rate": cfg.sample_rate,
        "vad_mode": cfg.vad_mode,
        "min_confidence": cfg.min_confidence,
        "silence_timeout_ms": cfg.silence_timeout_ms,
    }


@router.put("/config")
async def voice_config_put(request: Request, body: dict) -> JSONResponse:
    """热更新配置。配置无效返 400。"""
    try:
        result = await _get_svc(request).update_config(body)
        return JSONResponse(content=result)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_INPUT", "message": str(e)}},
        )


@router.get("/transcriptions")
async def voice_transcriptions(request: Request, limit: int = 50) -> list[dict]:
    """获取转录历史。"""
    return await _get_svc(request).get_transcriptions(limit=limit)


@router.get("/devices")
async def voice_devices(request: Request) -> list[dict]:
    """列出可用麦克风设备。"""
    return await _get_svc(request).get_devices()
