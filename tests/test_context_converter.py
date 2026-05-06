"""测试: DrivingContextInput → context dict 转换。"""

from app.schemas.context_converter import input_to_context_dict


def _make_input():
    """构造模拟 DrivingContextInput。"""

    class MockGeo:
        latitude = 0.0
        longitude = 0.0
        address = ""
        speed_kmh = 0.0

    class MockDriver:
        emotion = None
        workload = None
        fatigue_level = None

    class MockSpatial:
        current_location = None
        destination = None
        eta_minutes = None
        heading = None

    class MockInput:
        driver = MockDriver()
        spatial = MockSpatial()

    return MockInput()


def test_full_input():
    """全字段输入→完整 dict。"""

    class MockLoc:
        latitude = 39.9
        longitude = 116.4
        address = "天安门"
        speed_kmh = 60.0

    class MockDriver:
        emotion = "neutral"
        workload = "normal"
        fatigue_level = 0.3

    class MockSpatial:
        current_location = MockLoc()
        destination = MockLoc()
        eta_minutes = 30.0
        heading = 90.0

    class MockTraffic:
        def __init__(self):
            self.congestion_level = "moderate"
            self.incidents = ["accident_a"]
            self.estimated_delay_minutes = 15

    inp = _make_input()
    inp.scenario = "highway"
    inp.driver = MockDriver()
    inp.spatial = MockSpatial()
    inp.traffic = MockTraffic()

    result = input_to_context_dict(inp)
    assert result["scenario"] == "highway"
    assert result["driver"]["emotion"] == "neutral"
    assert result["driver"]["fatigue_level"] == 0.3
    assert result["spatial"]["current_location"]["latitude"] == 39.9
    assert result["spatial"]["destination"]["latitude"] == 39.9
    assert result["spatial"]["eta_minutes"] == 30.0
    assert result["traffic"]["incidents"] == ["accident_a"]


def test_minimal_input():
    """最少字段输入→driver/spatial/traffic 为空 dict。"""
    inp = _make_input()
    inp.scenario = "parked"
    result = input_to_context_dict(inp)
    assert result["scenario"] == "parked"
    assert result["driver"] == {}
    assert result["spatial"] == {}
    assert result["traffic"] == {}
