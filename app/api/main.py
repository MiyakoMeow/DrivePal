"""FastAPI应用主入口."""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import os
import logging

from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.models.settings import get_chat_model, get_embedding_model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="知行车秘 - 车载AI智能体")

DATA_DIR = os.getenv("DATA_DIR", "data")


def _ensure_memory_module() -> MemoryModule:
    chat_model = get_chat_model()
    embedding_model = get_embedding_model()
    return MemoryModule(
        data_dir=DATA_DIR, embedding_model=embedding_model, chat_model=chat_model
    )


_memory_module: MemoryModule | None = None


def get_memory_module() -> MemoryModule:
    """获取或初始化记忆模块单例."""
    global _memory_module
    if _memory_module is None:
        _memory_module = _ensure_memory_module()
    return _memory_module


class QueryRequest(BaseModel):
    """用户查询请求."""

    query: str
    memory_mode: MemoryMode = MemoryMode.KEYWORD


class FeedbackRequest(BaseModel):
    """用户反馈请求."""

    event_id: str
    action: str
    modified_content: Optional[str] = None


@app.post("/api/query")
async def query(request: QueryRequest, mm: MemoryModule = Depends(get_memory_module)):
    """处理用户查询."""
    from app.agents.workflow import AgentWorkflow

    try:
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=request.memory_mode,
            memory_module=mm,
        )
        result, event_id = workflow.run(request.query)
        return {"result": result, "event_id": event_id}
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/feedback")
async def feedback(
    request: FeedbackRequest, mm: MemoryModule = Depends(get_memory_module)
):
    """提交用户反馈."""
    try:
        from app.memory.schemas import FeedbackData

        feedback = FeedbackData(
            action=request.action,
            modified_content=request.modified_content,
        )
        mm.update_feedback(request.event_id, feedback)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Feedback failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/experiment/report")
async def experiment_report():
    """获取实验报告."""
    from app.experiment.runner import ExperimentRunner

    runner = ExperimentRunner(DATA_DIR)
    return {"report": runner.generate_report()}


@app.get("/api/history")
async def history(limit: int = 10, mm: MemoryModule = Depends(get_memory_module)):
    """获取历史记录."""
    try:
        events = mm.get_history(limit=limit)
        return {"history": [e.model_dump() for e in events]}
    except Exception as e:
        logger.error(f"History retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
