"""记忆工作台主入口."""

import os
import uvicorn
from pathlib import Path
from app.api.main import app
from app.storage.init_data import init_storage


if __name__ == "__main__":
    init_storage(Path(os.getenv("DATA_DIR", "data")))
    uvicorn.run(app, host="0.0.0.0", port=8000)
