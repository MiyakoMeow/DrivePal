"""应用配置模块."""

import logging
import os
from pathlib import Path

DATA_ROOT = Path(os.getenv("DATA_DIR", "data"))
# 保留 DATA_DIR 别名，兼容现有模块引用
DATA_DIR = DATA_ROOT


def user_data_dir(user_id: str = "default") -> Path:
    """返回指定用户的 per-user 数据目录路径。校验 user_id 防止路径遍历。"""
    if not user_id or user_id in (".", "..") or "/" in user_id or "\\" in user_id:
        msg = f"Invalid user ID: {user_id!r}"
        raise ValueError(msg)
    return DATA_DIR / "users" / user_id


def setup_logging() -> None:
    """配置应用级日志。仅在进程入口调用一次。"""
    logging.basicConfig(level=logging.INFO)
