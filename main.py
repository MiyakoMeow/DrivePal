"""记忆工作台主入口."""

import uvicorn
from app.api.main import app


if __name__ == "__main__":
    host = os.getenv("UVICORN_HOST", "127.0.0.1")
    port = int(os.getenv("UVICORN_PORT", 34567))
    uvicorn.run(app, host=host, port=port)

