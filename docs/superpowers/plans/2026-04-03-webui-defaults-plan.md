# WebUI 默认值与时间同步改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改进 WebUI 时间信息显示与表单默认值

**Architecture:** 仅修改前端 webui/app.js 和 webui/index.html，不涉及后端变更。时间显示策略：页面加载时显示本地时间，后端连接后切换到后端时间并同步更新。

**Tech Stack:** Vanilla JavaScript, WebSocket

---

## File Structure

- **Modify:** `webui/app.js`
  - 初始化区域（文件开头，`class SimulationWS` 之前）
  - SimulationWS._onMessage 方法
  - 初始化区域（`simWS.connect()` 之后，`loadPresets()` 之前）
- **Modify:** `webui/index.html:18-19` (时钟初始值)

注意：行号需在实施时验证。

---

## Task 1: 添加后端时间同步标志和本地时间初始化

**Files:**
- Modify: `webui/app.js` (初始化区域，在 SimulationWS class 前)
- Modify: `webui/index.html:18-19`

- [ ] **Step 1: 添加 hasReceivedBackendTime 标志、initLocalTime 函数并在末尾调用**

在 `class SimulationWS {` 之前添加：

```javascript
let hasReceivedBackendTime = false;
function initLocalTime() {
    const now = new Date();
    document.getElementById('clockDisplay').textContent = now.toLocaleTimeString('zh-CN', {hour12: false});
    document.getElementById('clockDate').textContent = now.toLocaleDateString('zh-CN');
}
initLocalTime();
```

- [ ] **Step 2: 修改 HTML 删除静态初始值**

将 `webui/index.html` 中：
```html
<div class="clock-display" id="clockDisplay">--:--:--</div>
<div class="clock-date" id="clockDate">----/--/--</div>
```

替换为：
```html
<div class="clock-display" id="clockDisplay"></div>
<div class="clock-date" id="clockDate"></div>
```

- [ ] **Step 3: Commit**

```bash
git add webui/app.js webui/index.html
git commit -m "feat(webui): show local time on page load before backend connects"
```

---

## Task 2: 修改 clock_tick 处理逻辑（首次 tick 时填充 simDate/simTime）

**Files:**
- Modify: `webui/app.js` (SimulationWS._onMessage 方法)

- [ ] **Step 1: 修改 _onMessage 中 clock_tick 分支，仅在首次 tick 时填充输入框**

将现有的 `clock_tick` 处理分支：
```javascript
if (msg.type === 'clock_tick') {
    const dt = new Date(msg.time);
    document.getElementById('clockDisplay').textContent = dt.toLocaleTimeString('zh-CN', {hour12: false});
    document.getElementById('clockDate').textContent = dt.toLocaleDateString('zh-CN');
}
```

替换为：
```javascript
if (msg.type === 'clock_tick') {
    const dt = new Date(msg.time);
    document.getElementById('clockDisplay').textContent = dt.toLocaleTimeString('zh-CN', {hour12: false});
    document.getElementById('clockDate').textContent = dt.toLocaleDateString('zh-CN');
    
    if (!hasReceivedBackendTime) {
        hasReceivedBackendTime = true;
        const dateStr = dt.toISOString().split('T')[0];
        const timeStr = dt.toTimeString().split(' ')[0];
        const simDateInput = document.getElementById('simDate');
        const simTimeInput = document.getElementById('simTime');
        if (!simDateInput.value) simDateInput.value = dateStr;
        if (!simTimeInput.value) simTimeInput.value = timeStr;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add webui/app.js
git commit -m "feat(webui): sync simDate/simTime from backend on first clock_tick"
```

---

## Task 3: 添加表单字段默认值

**Files:**
- Modify: `webui/app.js` (初始化区域，在 `simWS.connect()` 和 `notifyWS.connect()` 之后，`loadPresets()` 之前)

- [ ] **Step 1: 在 loadPresets(); 之前添加默认值设置**

在 `simWS.connect();` 和 `notifyWS.connect();` 之后，`loadPresets();` 之前添加：

```javascript
document.getElementById('ctx-emotion').value = 'neutral';
document.getElementById('ctx-workload').value = 'normal';
document.getElementById('ctx-fatigueLevel').value = '0';
document.getElementById('ctx-lat').value = '39.9042';
document.getElementById('ctx-lng').value = '116.4074';
document.getElementById('ctx-speedKmh').value = '0';
document.getElementById('ctx-congestionLevel').value = 'smooth';
document.getElementById('ctx-delayMinutes').value = '0';
document.getElementById('ctx-scenario').value = 'city_driving';
```

- [ ] **Step 2: Commit**

```bash
git add webui/app.js
git commit -m "feat(webui): set reasonable default values for form fields"
```

---

## Task 4: 验证

**Files:**
- Modify: 无

- [ ] **Step 1: 运行 lint 检查**

```bash
uv run ruff check --fix webui/app.js
uv run ruff format webui/app.js
```

- [ ] **Step 2: 启动应用并测试**

```bash
uv run python main.py
```

验证项：
1. 页面加载后立即显示本地当前时间（秒级精度）
2. WebSocket 连接后时钟切换到后端时间
3. `simDate` 和 `simTime` 输入框被填充（仅在空时填充）
4. 表单字段默认值正确：emotion=neutral, workload=normal, fatigueLevel=0, lat/lng=北京坐标, speedKmh=0, congestionLevel=smooth, delayMinutes=0, scenario=city_driving
5. 断开 WebSocket 后时钟保持不变
6. 控制台无报错

- [ ] **Step 3: 运行测试（如有）**

```bash
uv run pytest tests/ -v
```
