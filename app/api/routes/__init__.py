"""REST API 路由汇总."""

from fastapi import APIRouter

from app.api.routes.data import router as data_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.presets import router as presets_router
from app.api.routes.query import router as query_router
from app.api.routes.reminders import router as reminders_router
from app.api.routes.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(data_router, tags=["data"])
api_router.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
api_router.include_router(presets_router, prefix="/presets", tags=["presets"])
api_router.include_router(query_router, prefix="/query", tags=["query"])
api_router.include_router(reminders_router, prefix="/reminders", tags=["reminders"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
