import uvicorn
from app.api.main import app
from fastapi.responses import FileResponse
from pathlib import Path

webui_path = Path(__file__).parent / "webui"


@app.get("/")
async def root():
    return FileResponse(webui_path / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
