# WebUI 默认值与时间同步改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改进 WebUI 时间信息显示与表单默认值

**Architecture:** 仅修改前端 webui/app.js，不涉及后端变更。时间显示策略：页面加载时显示本地时间，后端连接后切换到后端时间并同步更新。

**Tech Stack:** Vanilla JavaScript, WebSocket

---

## File Structure

- **Modify:** `webui/app.js:262-291` (SimulationWS class)
- **Modify:** `webui/app.js:385-389` (initialization section)

---

## Task 1: 添加后端时间同步标志

**Files:**
- Modify: `webui/app.js` (在 SimulationWS class 前添加变量)

- [ ] **Step 1: 添加 hasReceivedBackendTime 标志**

在第 262 行 `class SimulationWS {` 之前添加：

```javascript
let hasReceivedBackendTime = false;
```

- [ ] **Step 2: Commit**

```bash
git add webui/app.js
git commit -m "feat(webui): add hasReceivedBackendTime flag"
```

---

## Task 2: 修改 clock_tick 处理逻辑

**Files:**
- Modify: `webui/app.js:283-290`

- [ ] **Step 1: 修改 _onMessage 中 clock_tick 分支**

将第 284-287 行：
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
- Modify: `webui/app.js:385-389` (initialization section)

- [ ] **Step 1: 在 loadPresets(); 之前添加默认值设置**

将第 388-389 行：
```javascript
loadPresets();
loadHistory();
```

替换为：
```javascript
document.getElementById('ctx-emotion').value = 'neutral';
document.getElementById('ctx-workload').value = 'normal';
document.getElementById('ctx-lat').value = '39.9042';
document.getElementById('ctx-lng').value = '116.4074';
document.getElementById('ctx-congestionLevel').value = 'smooth';
document.getElementById('ctx-scenario').value = 'city_driving';

loadPresets();
loadHistory();
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

- [ ] **Step 1: 运行 lint 和 type check**

```bash
uv run ruff check --fix webui/app.js
uv run ruff format webui/app.js
```

- [ ] **Step 2: 启动应用并测试**

```bash
uv run python main.py
```

验证项：
1. 页面加载后时钟显示本地时间
2. WebSocket 连接后时钟切换到后端时间
3. `simDate` 和 `simTime` 输入框被填充
4. 表单字段（emotion=neutral, workload=normal, lat/lng=北京坐标等）显示默认值

- [ ] **Step 3: 运行测试（如有）**

```bash
uv run pytest tests/ -v
```
