"""记忆工作台主入口."""

import uvicorn
from app.api.main import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=40721)
