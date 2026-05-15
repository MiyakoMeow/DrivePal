"""工具注册表测试。"""

from app.tools.registry import ToolRegistry, ToolSpec


async def _fake_handler(params: dict) -> str:
    return f"ok:{params}"


def test_register_and_get():
    reg = ToolRegistry()
    spec = ToolSpec(
        name="test", description="test tool", input_schema={}, handler=_fake_handler
    )
    reg.register(spec)
    assert reg.get("test") is spec


def test_duplicate_register_raises():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="dup", description="", input_schema={}, handler=_fake_handler)
    )
    import pytest

    with pytest.raises(ValueError, match="already registered"):
        reg.register(
            ToolSpec(name="dup", description="", input_schema={}, handler=_fake_handler)
        )
