# 数据模型

`app/schemas/`。Pydantic Literal 约束合法值。

## 驾驶上下文 — `context.py`

- **DriverState**: emotion (neutral/anxious/fatigued/calm/angry), workload (low/normal/high/overloaded), fatigue_level (0~1)
- **GeoLocation**: latitude, longitude, address, speed_kmh
- **SpatioTemporalContext**: current_location, destination, eta_minutes, heading
- **TrafficCondition**: congestion_level (smooth/slow/congested/blocked), incidents, estimated_delay_minutes
- **DrivingContext**: driver + spatial + traffic + scenario (parked/city_driving/highway/traffic_jam) + passengers (list[str])
- **ScenarioPreset**: id (uuid hex[:12]), name, context (DrivingContext), created_at (ISO datetime)

## 查询 schema — `query.py`

SSE 查询端点 `POST /query/stream` 的输入/输出 schema，文档化契约参考。

- **ProcessQueryRequest**: query (str), memory_mode (MemoryMode, 默认 MEMORY_BANK), context (dict | None), current_user (str, 默认 "default"), session_id (str | None)
- **ProcessQueryResult**: status (str, 默认 "delivered"，可能值 delivered/pending/suppressed 见注释), event_id, session_id, result (dict | None), pending_reminder_id, trigger_text, reason, cancelled (bool | None)
