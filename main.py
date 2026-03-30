"""记忆工作台主入口."""

import os
import uvicorn
from pathlib import Path
from fastapi.responses import FileResponse
from app.api.main import app
from app.storage.init_data import init_storage

webui_path = Path(__file__).parent / "webui"


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(webui_path / "index.html")


if __name__ == "__main__":
    init_storage(Path(os.getenv("DATA_DIR", "data")))
    uvicorn.run(app, host="0.0.0.0", port=8000)
