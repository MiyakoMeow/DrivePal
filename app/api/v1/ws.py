"""WebSocket 实时端点：查询流式 + 提醒推送."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.workflow import AgentWorkflow
from app.api.v1.ws_manager import ws_manager
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module

logger = logging.getLogger(__name__)
router = APIRouter()

_HEARTBEAT_TIMEOUT = 60.0


@router.websocket("")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点。

    BaseHTTPMiddleware 不处理 WS 连接，从 ws.headers 直接读 X-User-Id。
    """
    user_id = ws.headers.get("x-user-id", "default")
    await ws_manager.connect(ws, user_id)
    logger.info("WS connected: user=%s", user_id)

    try:
        while True:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_HEARTBEAT_TIMEOUT)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager.send_to(
                    ws,
                    {
                        "type": "error",
                        "payload": {
                            "code": "INVALID_JSON",
                            "message": "Malformed JSON",
                        },
                    },
                )
                continue
            msg_type = msg.get("type")

            if msg_type == "ping":
                await ws_manager.send_to(ws, {"type": "pong", "payload": {}})

            elif msg_type == "query":
                payload = msg.get("payload", {})
                await _handle_query(ws, user_id, payload)

            else:
                await ws_manager.send_to(
                    ws,
                    {
                        "type": "error",
                        "payload": {
                            "code": "INVALID_MESSAGE",
                            "message": f"Unknown type: {msg_type}",
                        },
                    },
                )

    except TimeoutError:
        logger.info("WS heartbeat timeout: user=%s", user_id)
    except WebSocketDisconnect:
        logger.info("WS disconnected: user=%s", user_id)
    except Exception:
        logger.exception("WS error: user=%s", user_id)
    finally:
        ws_manager.disconnect(ws, user_id)


async def _handle_query(ws: WebSocket, user_id: str, payload: dict) -> None:
    """处理查询消息，流式回推各阶段。"""
    query = payload.get("query", "")
    context_raw = payload.get("context")
    session_id = payload.get("session_id")

    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_module=mm,
        current_user=user_id,
    )

    try:
        async for event in workflow.run_stream(
            query, context_raw, session_id=session_id
        ):
            await ws_manager.send_to(
                ws,
                {
                    "type": event["event"],
                    "payload": event["data"],
                },
            )
    except Exception:
        logger.exception("WS query failed")
        await ws_manager.send_to(
            ws,
            {
                "type": "error",
                "payload": {
                    "code": "QUERY_FAILED",
                    "message": "Query processing failed",
                },
            },
        )
