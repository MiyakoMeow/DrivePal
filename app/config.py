"""应用配置模块."""

import logging
import os
import tomllib
from pathlib import Path

import tomli_w

logger = logging.getLogger(__name__)

DATA_ROOT = Path(os.getenv("DATA_DIR", "data"))
# 保留 DATA_DIR 别名，兼容现有模块引用
DATA_DIR = DATA_ROOT

# 缓存配置根路径（list 容器避免 PLW0603 global 警告）
_CONFIG_ROOT: list[Path | None] = [None]


def user_data_dir(user_id: str = "default") -> Path:
    """返回指定用户的 per-user 数据目录路径。校验 user_id 防止路径遍历。"""
    if not user_id or user_id in (".", "..") or "/" in user_id or "\\" in user_id:
        msg = f"Invalid user ID: {user_id!r}"
        raise ValueError(msg)
    return DATA_DIR / "users" / user_id


def setup_logging() -> None:
    """配置应用级日志。仅在进程入口调用一次。"""
    logging.basicConfig(level=logging.INFO)


def get_config_root() -> Path:
    """返回配置根目录路径。

    优先环境变量 CONFIG_DIR，默认项目根下 config/。
    结果缓存避免重复解析。
    """
    if _CONFIG_ROOT[0] is not None:
        return _CONFIG_ROOT[0]
    env = os.environ.get("CONFIG_DIR")
    if env:
        _CONFIG_ROOT[0] = Path(env).resolve()
    else:
        _CONFIG_ROOT[0] = Path(__file__).resolve().parent.parent / "config"
    return _CONFIG_ROOT[0]


def reset_config_root_cache() -> None:
    """重置配置根路径缓存（仅测试用）。"""
    _CONFIG_ROOT[0] = None


def ensure_config(path: Path, default_dict: dict) -> dict:
    """确保配置文件存在，缺失则从 default_dict 生成。返回 tomllib 解析结果。

    所有 I/O 异常均日志警告并返回默认 dict，不传播。
    mkdir/PermissionError/读失败均不会影响调用方正常运行。

    写入使用原子操作（tmp 文件 + rename），防止 xdist 多 worker
    同时访问时读到空文件导致配置丢失。
    """
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            logger.warning("Cannot create config dir %s: %s", path.parent, e)
            return dict(default_dict)
        try:
            tmp = path.with_suffix(".tmp")
            with tmp.open("wb") as f:
                tomli_w.dump(default_dict, f)
            tmp.rename(path)
        except (OSError, PermissionError) as e:
            logger.warning("Cannot write %s: %s, using defaults", path, e)
            return dict(default_dict)
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning("Failed to read %s: %s, using defaults", path, e)
        return dict(default_dict)
