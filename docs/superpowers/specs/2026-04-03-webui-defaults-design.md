# WebUI 默认值与时间同步改进设计

## 1. 概述

本文档描述对知行车秘 WebUI 的两项改进：
1. 时间信息的初始化显示与后端同步机制
2. 表单字段的合理默认值设置

## 2. 时间信息显示与同步

### 2.1 目标

- 页面加载时即能显示有意义的时间信息
- 与后端严格同步，仅依赖后端广播的 `clock_tick` 消息
- 后端未连接时使用本地时间作为临时显示

### 2.2 行为规格

| 场景 | 时钟显示 | simDate 输入框 | simTime 输入框 |
|------|----------|----------------|---------------|
| 页面加载，后端未连接 | 本地当前时间 | 空 | 空 |
| 后端连接，首个 clock_tick 到达 | 后端时间 | 后端日期 | 后端时间 |
| 正常运行 | 每秒随 clock_tick 更新 | 用户手动设置 | 用户手动设置 |

### 2.3 实现要点

- `clockDisplay`: 初始 `--:--:--`，后端连接后显示后端时间
- `clockDate`: 初始 `----/--/--`，后端连接后显示后端日期
- 添加 `hasReceivedBackendTime` 标志，区分本地时间和后端时间
- `simDate`/`simTime` 仅在后端首次广播时填充默认值

### 2.4 WebSocket 消息处理

```
clock_tick 消息格式:
{
  "type": "clock_tick",
  "time": "2026-04-03T10:30:00+08:00",  // ISO 格式
  "time_scale": 1.0
}
```

## 3. 表单字段默认值

### 3.1 目标

- 网页加载时表单字段有合理的默认值
- 减少用户操作步骤，提升使用体验

### 3.2 默认值列表

| 字段 ID | 默认值 | 说明 |
|---------|--------|------|
| ctx-emotion | `neutral` | 正常 |
| ctx-workload | `normal` | 正常 |
| ctx-fatigueLevel | `0` | 无疲劳 |
| ctx-lat | `39.9042` | 北京纬度 |
| ctx-lng | `116.4074` | 北京经度 |
| ctx-speedKmh | `0` | 静止 |
| ctx-congestionLevel | `smooth` | 畅通 |
| ctx-delayMinutes | `0` | 无延误 |
| ctx-scenario | `city_driving` | 城市道路 |

### 3.3 实现方式

- 在 `app.js` 初始化时直接设置 `document.getElementById('ctx-xxx').value = 'yyy'`
- 位置：在 `simWS.connect()` 和 `notifyWS.connect()` 之后，`loadPresets()` 之前

## 4. 文件变更

### 4.1 webui/app.js

**变更点：**
1. 添加 `hasReceivedBackendTime` 变量（初始 `false`）
2. 修改 `SimulationWS._onMessage` 中 `clock_tick` 处理逻辑：
   - 首次收到时，填充 `simDate` 和 `simTime`
   - 后续收到时，仅更新显示
3. 在初始化区域添加表单字段默认值设置

### 4.2 无需后端变更

本设计不涉及后端变更，所有行为调整在前端完成。

## 5. 测试要点

1. 页面加载后立即检查时钟显示是否为本地时间
2. 等待 WebSocket 连接后，检查时钟是否切换到后端时间
3. 首次连接后，`simDate` 和 `simTime` 是否被填充
4. 各表单字段默认值是否正确设置
5. 断开 WebSocket 后，时钟显示是否保持不变
