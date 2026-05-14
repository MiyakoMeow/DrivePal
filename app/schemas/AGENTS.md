# 数据模型

`app/schemas/` — Pydantic模型。合法值由 Literal/Field 约束。

## 驾驶上下文 (`context.py`)

- **DriverState**: emotion(neutral/anxious/fatigued/calm/angry), workload(low/normal/high/overloaded), fatigue_level(0~1)
- **GeoLocation**: latitude(ge=-90,le=90), longitude(ge=-180,le=180), address, speed_kmh(ge=0)
- **SpatioTemporalContext**: current_location, destination, eta_minutes(ge=0), heading(0~360)
- **TrafficCondition**: congestion_level(smooth/slow/congested/blocked), incidents, estimated_delay_minutes
- **DrivingContext**: driver + spatial + traffic + scenario(parked/city_driving/highway/traffic_jam) + passengers
- **ScenarioPreset**: id(uuid hex[:12]), name, context, created_at

## 查询Schema (`query.py`)

- **ProcessQueryRequest**: query, context(DrivingContext|None), current_user, session_id
- **ProcessQueryResult**: status(delivered/pending/suppressed), event_id, session_id, result, pending_reminder_id, trigger_text, reason, cancelled
