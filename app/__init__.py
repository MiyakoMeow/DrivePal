import os
from app.storage.init_data import init_storage

init_storage(os.getenv("DATA_DIR", "data"))
