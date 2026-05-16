"""消融实验模块集中配置 —— TOML + 环境变量双通道。"""

from __future__ import annotations

import logging
import os
from functools import cache
from typing import Any

from app.config import ensure_config, get_config_root

logger = logging.getLogger(__name__)

_EXPERIMENTS_TOML_DEFAULTS: dict[str, Any] = {
    "timeouts": {
        "context": 30.0,
        "joint_decision": 120.0,
        "execution": 30.0,
    },
}


@cache
def load_experiments_toml() -> dict[str, Any]:
    """加载 experiments.toml，缺失则从默认值生成并持久化。结果缓存避免重复 I/O。

    TOML 文件位于 {config_root}/experiments.toml，可通过 CONFIG_DIR 环境变量重定向。
    """
    path = get_config_root() / "experiments.toml"
    return ensure_config(path, _EXPERIMENTS_TOML_DEFAULTS)


def load_stage_timeouts() -> dict[str, float]:
    """读取阶段超时配置，优先级：环境变量 > TOML > 代码默认值。

    环境变量键：
      ABLATION_TIMEOUT_CONTEXT, ABLATION_TIMEOUT_JOINT_DECISION, ABLATION_TIMEOUT_EXECUTION

    TOML 节：
      [timeouts]
      context = 30.0
      joint_decision = 120.0
      execution = 30.0

    返回 dict 保证三键俱全且值为正 float（坏值回退默认）。
    """
    toml = load_experiments_toml()
    raw = toml.get("timeouts", {})
    defaults: dict[str, float] = _EXPERIMENTS_TOML_DEFAULTS["timeouts"]
    env_overrides = {
        "context": "ABLATION_TIMEOUT_CONTEXT",
        "joint_decision": "ABLATION_TIMEOUT_JOINT_DECISION",
        "execution": "ABLATION_TIMEOUT_EXECUTION",
    }
    timeouts: dict[str, float] = {}
    for key, default in defaults.items():
        val = os.environ.get(env_overrides[key])
        if val is not None:
            try:
                timeouts[key] = float(val)
                continue
            except ValueError:
                logger.warning(
                    "Invalid %s=%r, falling back to config default",
                    env_overrides[key],
                    val,
                )
        raw_val = raw.get(key, default)
        timeouts[key] = float(raw_val) if isinstance(raw_val, (int, float)) else default
    return timeouts


# 模块级常量，导入即初始化，@cache 保证 TOML 仅读一次
STAGE_TIMEOUT: dict[str, float] = load_stage_timeouts()
"""阶段超时（秒）。源自 experiments.toml [timeouts]，环境变量可逐项覆盖。"""
