"""主动调度器配置."""

from dataclasses import dataclass

from app.config import ensure_config, get_config_root


@dataclass
class SchedulerConfig:
    """主动调度器配置。缺省值与 scheduler.toml 默认一致。"""

    tick_interval_seconds: float = 15.0
    debounce_seconds: float = 30.0
    enable_periodic_review: bool = True
    review_time: str = "08:00"
    location_proximity_meters: int = 500
    fatigue_delta_threshold: float = 0.1

    @classmethod
    def _toml_defaults(cls) -> dict:
        """从 dataclass 默认值生成 TOML dict。默认值唯一来源为字段默认。"""
        cfg = cls()
        return {
            "scheduler": {
                "tick_interval_seconds": cfg.tick_interval_seconds,
                "debounce_seconds": cfg.debounce_seconds,
                "enable_periodic_review": cfg.enable_periodic_review,
                "review_time": cfg.review_time,
                "location_proximity_meters": cfg.location_proximity_meters,
                "context_monitor": {
                    "fatigue_delta_threshold": cfg.fatigue_delta_threshold,
                },
            },
        }

    @classmethod
    def load(cls) -> SchedulerConfig:
        """加载 scheduler.toml，文件缺失则自动生成。"""
        path = get_config_root() / "scheduler.toml"
        raw = ensure_config(path, cls._toml_defaults())
        raw_sched = raw.get("scheduler")
        sched = raw_sched if isinstance(raw_sched, dict) else {}
        raw_ctx = sched.get("context_monitor")
        ctx = raw_ctx if isinstance(raw_ctx, dict) else {}
        return cls(
            tick_interval_seconds=sched.get(
                "tick_interval_seconds", cls.tick_interval_seconds
            ),
            debounce_seconds=sched.get("debounce_seconds", cls.debounce_seconds),
            enable_periodic_review=sched.get(
                "enable_periodic_review", cls.enable_periodic_review
            ),
            review_time=str(sched.get("review_time", cls.review_time)),
            location_proximity_meters=sched.get(
                "location_proximity_meters", cls.location_proximity_meters
            ),
            fatigue_delta_threshold=ctx.get(
                "fatigue_delta_threshold", cls.fatigue_delta_threshold
            ),
        )
