"""记忆工作台主入口."""

import os

import uvicorn

from app.api.main import app
from app.config import setup_logging

if __name__ == "__main__":
    setup_logging()
    host = os.getenv("UVICORN_HOST", "127.0.0.1")
    port = int(os.getenv("UVICORN_PORT", "34567"))
    uvicorn.run(app, host=host, port=port)
