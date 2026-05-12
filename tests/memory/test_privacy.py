"""隐私保护模块测试."""

from app.memory.privacy import sanitize_context, sanitize_location


def test_latitude_truncated():
    lat, _, _ = sanitize_location(31.230416, 121.473701, "上海市浦东新区世纪大道100号")
    assert lat == 31.23


def test_longitude_truncated():
    _, lon, _ = sanitize_location(31.230416, 121.473701, "")
    assert lon == 121.47


def test_address_street_level():
    _, _, addr = sanitize_location(0, 0, "北京市海淀区中关村大街1号, 创新大厦")
    assert "海淀区" in addr
    assert "创新大厦" not in addr


def test_address_no_comma_preserved():
    _, _, addr = sanitize_location(0, 0, "上海市浦东新区")
    assert addr == "上海市浦东新区"


def test_sanitize_context_handles_none():
    """无 spatial 字段的 context 原样返回."""
    assert sanitize_context({}) == {}
    assert sanitize_context({"scenario": "highway"}) == {"scenario": "highway"}


def test_sanitize_context_truncates_locations():
    """spatial 中的 current_location 和 destination 均被脱敏."""
    ctx = {
        "spatial": {
            "current_location": {
                "latitude": 31.234567,
                "longitude": 121.456789,
                "address": "上海市浦东新区世纪大道1号, 上海中心",
            },
            "destination": {
                "latitude": 31.345678,
                "longitude": 121.567890,
                "address": "北京市海淀区中关村",
            },
        },
    }
    result = sanitize_context(ctx)
    cl = result["spatial"]["current_location"]
    assert cl["latitude"] == 31.23
    assert cl["longitude"] == 121.46
    assert "上海中心" not in cl["address"]
    dl = result["spatial"]["destination"]
    assert dl["latitude"] == 31.35
    assert dl["longitude"] == 121.57
