# app/schemas - 驾驶上下文数据模型

`context.py`。Pydantic Literal 约束合法值。

## 数据模型

| 模型 | 字段 | 说明 |
|------|------|------|
| `DriverState` | emotion, workload, fatigue_level | emotion: neutral/anxious/fatigued/calm/angry; workload: low/normal/high/overloaded; fatigue_level: 0~1 |
| `GeoLocation` | latitude, longitude, address, speed_kmh | 位置信息 |
| `SpatioTemporalContext` | current_location, destination, eta_minutes, heading | 时空上下文 |
| `TrafficCondition` | congestion_level, incidents, estimated_delay_minutes | congestion_level: smooth/slow/congested/blocked |
| `DrivingContext` | driver, spatial, traffic, scenario, passengers | scenario: parked/city_driving/highway/traffic_jam; passengers: list[str] |
| `ScenarioPreset` | id, name, context, created_at | 场景预设 |

## 用途

- Context Agent 输出/外部注入的目标格式
- API 层输入转换的目标类型（`converters.py` → `model_validate()`）
- 规则引擎条件判断依据
