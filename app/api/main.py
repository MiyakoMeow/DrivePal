"""FastAPI应用主入口."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

from app.memory.memory import MemoryModule
from app.models.settings import get_chat_model, get_embedding_model
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="知行车秘 - 车载AI智能体")

DATA_DIR = os.getenv("DATA_DIR", "data")

_chat_model = get_chat_model()
_embedding_model = get_embedding_model()
_memory_module = MemoryModule(
    data_dir=DATA_DIR, embedding_model=_embedding_model, chat_model=_chat_model
)


class QueryRequest(BaseModel):
    """用户查询请求."""

    query: str
    memory_mode: Optional[str] = "keyword"


class FeedbackRequest(BaseModel):
    """用户反馈请求."""

    event_id: str
    action: str
    modified_content: Optional[str] = None


@app.post("/api/query")
async def query(request: QueryRequest):
    """处理用户查询."""
    from app.agents.workflow import AgentWorkflow

    try:
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=request.memory_mode or "keyword",
            memory_module=_memory_module,
        )
        result, event_id = workflow.run(request.query)
        return {"result": result, "event_id": event_id}
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/feedback")
async def feedback(request: FeedbackRequest):
    """提交用户反馈."""
    try:
        _memory_module.update_feedback(
            request.event_id,
            {"action": request.action, "modified_content": request.modified_content},
        )
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
async def history(limit: int = 10):
    """获取历史记录."""
    try:
        history = _memory_module.get_history(limit=limit)
        return {"history": history}
    except Exception as e:
        logger.error(f"History retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
