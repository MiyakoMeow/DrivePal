"""应用配置模块."""

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
