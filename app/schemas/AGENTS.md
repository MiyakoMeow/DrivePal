# 上下文数据模型

`app/schemas/context.py`。Pydantic Literal 约束合法值。

- **DriverState**: emotion (neutral/anxious/fatigued/calm/angry), workload (low/normal/high/overloaded), fatigue_level (0~1)
- **GeoLocation**: latitude, longitude, address, speed_kmh
- **SpatioTemporalContext**: current_location, destination, eta_minutes, heading
- **TrafficCondition**: congestion_level (smooth/slow/congested/blocked), incidents, delay_minutes
- **DrivingContext**: driver + spatial + traffic + scenario (parked/city_driving/highway/traffic_jam)
