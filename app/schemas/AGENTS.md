# 数据模型

`app/schemas/`。Pydantic 模型，合法值多由 Literal 或 Field 约束（ProcessQueryResult.status 例外，以注释标注）。

## 驾驶上下文 — `context.py`

- **DriverState**: emotion (neutral/anxious/fatigued/calm/angry), workload (low/normal/high/overloaded), fatigue_level (0~1)
- **GeoLocation**: latitude (ge=-90, le=90), longitude (ge=-180, le=180), address, speed_kmh (ge=0)
- **SpatioTemporalContext**: current_location, destination, eta_minutes (ge=0), heading (ge=0, le=360)
- **TrafficCondition**: congestion_level (smooth/slow/congested/blocked), incidents (list[str]), estimated_delay_minutes (int, ge=0)
- **DrivingContext**: driver (DriverState) + spatial (SpatioTemporalContext) + traffic (TrafficCondition) + scenario (parked/city_driving/highway/traffic_jam) + passengers (list[str])
- **ScenarioPreset**: id (uuid hex[:12]), name, context (DrivingContext), created_at (ISO datetime)

## 查询 schema — `query.py`

SSE 查询端点 `POST /query/stream` 的输入/输出 schema，文档化契约参考。

- **ProcessQueryRequest**: query (str), context (DrivingContext | None, 默认 None), current_user (str, 默认 "default"), session_id (str | None)
- **ProcessQueryResult**: status (str, 默认 "delivered"，可能值 delivered/pending/suppressed 见注释), event_id (str | None, 默认 None), session_id (str | None, 默认 None), result (dict | None, 默认 None), pending_reminder_id (str | None, 默认 None), trigger_text (str | None, 默认 None), reason (str | None, 默认 None), cancelled (bool | None, 默认 None)
