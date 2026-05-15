"""工具调用框架配置."""

from dataclasses import asdict, dataclass, field

from app.config import ensure_config, get_config_root


@dataclass
class NavigationToolConfig:
    """导航工具配置。"""

    enabled: bool = True
    require_voice_confirmation_driving: bool = True


@dataclass
class CommunicationToolConfig:
    """通信工具配置。"""

    enabled: bool = True
    max_message_length: int = 200


@dataclass
class VehicleToolConfig:
    """车控工具配置。"""

    enabled: bool = False
    temperature_min: int = 16
    temperature_max: int = 32


@dataclass
class MemoryQueryToolConfig:
    """记忆查询工具配置。"""

    enabled: bool = True
    max_results: int = 5


@dataclass
class ToolsConfig:
    """工具配置集合。缺省值与 tools.toml 默认一致。"""

    navigation: NavigationToolConfig = field(default_factory=NavigationToolConfig)
    communication: CommunicationToolConfig = field(
        default_factory=CommunicationToolConfig
    )
    vehicle: VehicleToolConfig = field(default_factory=VehicleToolConfig)
    memory_query: MemoryQueryToolConfig = field(default_factory=MemoryQueryToolConfig)

    @classmethod
    def _toml_defaults(cls) -> dict:
        """从 dataclass 默认值生成 TOML dict。默认值唯一来源为 dataclass 字段默认。"""
        cfg = cls()
        return {
            "tools": {
                "navigation": asdict(cfg.navigation),
                "communication": asdict(cfg.communication),
                "vehicle": asdict(cfg.vehicle),
                "memory_query": asdict(cfg.memory_query),
            },
        }

    @classmethod
    def load(cls) -> ToolsConfig:
        """加载 tools.toml，文件缺失则自动生成。

        不缓存：许可瞬态 I/O 错误后自动恢复，防止错误的默认值被 pin 住。
        文件仅 267 字节，重复读取的开销可忽略。
        """
        path = get_config_root() / "tools.toml"
        raw = ensure_config(path, cls._toml_defaults())
        tools_data = raw.get("tools", {})

        def _sub(name: str) -> dict:
            value = tools_data.get(name)
            return value if isinstance(value, dict) else {}

        return cls(
            navigation=NavigationToolConfig(
                enabled=_sub("navigation").get("enabled", True),
                require_voice_confirmation_driving=_sub("navigation").get(
                    "require_voice_confirmation_driving", True
                ),
            ),
            communication=CommunicationToolConfig(
                enabled=_sub("communication").get("enabled", True),
                max_message_length=_sub("communication").get("max_message_length", 200),
            ),
            vehicle=VehicleToolConfig(
                enabled=_sub("vehicle").get("enabled", False),
                temperature_min=_sub("vehicle").get("temperature_min", 16),
                temperature_max=_sub("vehicle").get("temperature_max", 32),
            ),
            memory_query=MemoryQueryToolConfig(
                enabled=_sub("memory_query").get("enabled", True),
                max_results=_sub("memory_query").get("max_results", 5),
            ),
        )
