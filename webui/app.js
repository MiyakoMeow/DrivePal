let currentEventId = null;

async function graphql(query, variables) {
    const resp = await fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, variables })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    const json = await resp.json();
    if (json.errors && json.errors.length) {
        throw new Error(json.errors.map(e => e.message).join('; '));
    }
    return json.data;
}

function getContextInput() {
    const emotion = document.getElementById('ctx-emotion').value;
    const workload = document.getElementById('ctx-workload').value;
    const fatigueLevel = parseFloat(document.getElementById('ctx-fatigueLevel').value);
    const lat = document.getElementById('ctx-lat').value;
    const lng = document.getElementById('ctx-lng').value;
    const address = document.getElementById('ctx-address').value;
    const speedKmh = document.getElementById('ctx-speedKmh').value;
    const destAddress = document.getElementById('ctx-dest-address').value;
    const etaMinutes = document.getElementById('ctx-etaMinutes').value;
    const congestionLevel = document.getElementById('ctx-congestionLevel').value;
    const incidents = document.getElementById('ctx-incidents').value;
    const delayMinutes = document.getElementById('ctx-delayMinutes').value;
    const scenario = document.getElementById('ctx-scenario').value;

    const driver = {};
    if (emotion) driver.emotion = emotion;
    if (workload) driver.workload = workload;
    driver.fatigueLevel = fatigueLevel;

    const spatial = {};
    const curLoc = {};
    if (lat !== '') curLoc.latitude = parseFloat(lat);
    if (lng !== '') curLoc.longitude = parseFloat(lng);
    if (address) curLoc.address = address;
    if (speedKmh !== '') curLoc.speedKmh = parseFloat(speedKmh);
    if (Object.keys(curLoc).length) spatial.currentLocation = curLoc;

    const dest = {};
    if (destAddress) dest.address = destAddress;
    if (Object.keys(dest).length) spatial.destination = dest;

    if (etaMinutes !== '') spatial.etaMinutes = parseFloat(etaMinutes);

    const traffic = {};
    if (congestionLevel) traffic.congestionLevel = congestionLevel;
    if (incidents) traffic.incidents = [incidents];
    if (delayMinutes !== '') traffic.estimatedDelayMinutes = parseInt(delayMinutes, 10);

    const ctx = {};
    if (Object.keys(driver).length) ctx.driver = driver;
    if (Object.keys(spatial).length) ctx.spatial = spatial;
    if (Object.keys(traffic).length) ctx.traffic = traffic;
    if (scenario) ctx.scenario = scenario;

    return Object.keys(ctx).length ? ctx : null;
}

function fillForm(preset) {
    if (!preset) return;
    const ctx = preset.context || {};
    const d = ctx.driver || {};
    const s = ctx.spatial || {};
    const t = ctx.traffic || {};

    document.getElementById('ctx-emotion').value = d.emotion || '';
    document.getElementById('ctx-workload').value = d.workload || '';
    document.getElementById('ctx-fatigueLevel').value = d.fatigueLevel ?? 0;
    document.getElementById('fatigueVal').textContent = (d.fatigueLevel ?? 0).toFixed(1);

    const cl = s.currentLocation || {};
    document.getElementById('ctx-lat').value = cl.latitude ?? '';
    document.getElementById('ctx-lng').value = cl.longitude ?? '';
    document.getElementById('ctx-address').value = cl.address || '';
    document.getElementById('ctx-speedKmh').value = cl.speedKmh ?? '';

    const dest = s.destination || {};
    document.getElementById('ctx-dest-address').value = dest.address || '';
    document.getElementById('ctx-etaMinutes').value = s.etaMinutes ?? '';

    document.getElementById('ctx-congestionLevel').value = t.congestionLevel || '';
    document.getElementById('ctx-incidents').value = t.incidents || '';
    document.getElementById('ctx-delayMinutes').value = t.estimatedDelayMinutes ?? '';

    document.getElementById('ctx-scenario').value = ctx.scenario || '';
}

function clearForm() {
    document.getElementById('ctx-emotion').value = '';
    document.getElementById('ctx-workload').value = '';
    document.getElementById('ctx-fatigueLevel').value = 0;
    document.getElementById('fatigueVal').textContent = '0.0';
    document.getElementById('ctx-lat').value = '';
    document.getElementById('ctx-lng').value = '';
    document.getElementById('ctx-address').value = '';
    document.getElementById('ctx-speedKmh').value = '';
    document.getElementById('ctx-dest-address').value = '';
    document.getElementById('ctx-etaMinutes').value = '';
    document.getElementById('ctx-congestionLevel').value = '';
    document.getElementById('ctx-incidents').value = '';
    document.getElementById('ctx-delayMinutes').value = '';
    document.getElementById('ctx-scenario').value = '';
}

function formatJson(val) {
    if (val === null || val === undefined) return 'null';
    try {
        return JSON.stringify(val, null, 2);
    } catch {
        return String(val);
    }
}

function setLoading(on) {
    const btn = document.getElementById('sendBtn');
    btn.disabled = on;
    btn.innerHTML = on ? '<span class="spinner"></span>处理中...' : '发送';
}

async function loadPresets() {
    try {
        const data = await graphql(`{ scenarioPresets { id name context { driver { emotion workload fatigueLevel } spatial { currentLocation { latitude longitude address speedKmh } destination { latitude longitude address speedKmh } etaMinutes } traffic { congestionLevel incidents estimatedDelayMinutes } scenario } } }`);
        const sel = document.getElementById('presetSelect');
        sel.innerHTML = '<option value="">-- 选择预设 --</option>';
        (data.scenarioPresets || []).forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            opt.dataset.preset = JSON.stringify(p);
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load presets:', e);
    }
}

function loadPreset(id) {
    const sel = document.getElementById('presetSelect');
    const opt = sel.selectedOptions[0];
    if (!opt || !opt.dataset.preset) return;
    fillForm(JSON.parse(opt.dataset.preset));
}

async function savePreset() {
    const name = prompt('请输入预设名称:');
    if (!name) return;
    const context = getContextInput();
    if (!context) { alert('请至少填写一项上下文信息'); return; }
    try {
        await graphql(
            `mutation SavePreset($name: String!, $context: DrivingContextInput!) { saveScenarioPreset(input: { name: $name, context: $context }) { id name } }`,
            { name, context }
        );
        alert('预设已保存');
        loadPresets();
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}

async function sendQuery() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query) return;

    const memoryMode = document.getElementById('memoryMode').value;
    const context = getContextInput();

    setLoading(true);
    document.getElementById('feedbackRow').style.display = 'none';
    ['context', 'task', 'decision', 'execution'].forEach(s => {
        document.getElementById(`stage-${s}-body`).innerHTML = '<span class="empty-hint">处理中...</span>';
    });

    try {
        const data = await graphql(
            `mutation ProcessQuery($query: String!, $memoryMode: MemoryModeEnum!, $context: DrivingContextInput) {
                processQuery(input: { query: $query, memoryMode: $memoryMode, context: $context }) {
                    result eventId stages { context task decision execution }
                }
            }`,
            { query, memoryMode, context }
        );

        const res = data.processQuery;
        currentEventId = res.eventId;

        const stages = res.stages || {};
        document.getElementById('stage-context-body').textContent = formatJson(stages.context);
        document.getElementById('stage-task-body').textContent = formatJson(stages.task);
        document.getElementById('stage-decision-body').textContent = formatJson(stages.decision);
        document.getElementById('stage-execution-body').textContent = formatJson(stages.execution);

        if (currentEventId) {
            document.getElementById('feedbackRow').style.display = 'flex';
        }

        loadHistory();
    } catch (e) {
        ['context', 'task', 'decision', 'execution'].forEach(s => {
            const el = document.getElementById(`stage-${s}-body`);
            el.innerHTML = '<span class="error">Error: ' + escapeHtml(e.message) + '</span>';
        });
    } finally {
        setLoading(false);
    }
}

async function submitFeedback(action) {
    if (!currentEventId) return;
    try {
        await graphql(
            `mutation SubmitFeedback($eventId: String!, $action: String!) {
                submitFeedback(input: { eventId: $eventId, action: $action }) { status }
            }`,
            { eventId: currentEventId, action }
        );
        document.getElementById('feedbackRow').style.display = 'none';
    } catch (e) {
        alert('反馈提交失败: ' + e.message);
    }
}

async function loadHistory() {
    try {
        const mode = document.getElementById('memoryMode').value;
        const data = await graphql(
            `query GetHistory($limit: Int!, $memoryMode: MemoryModeEnum!) {
                history(limit: $limit, memoryMode: $memoryMode) { id content createdAt }
            }`,
            { limit: 10, memoryMode: mode }
        );
        const container = document.getElementById('historyList');
        const items = data.history || [];
        if (!items.length) {
            container.innerHTML = '<span class="empty-hint">暂无历史记录</span>';
            return;
        }
        container.innerHTML = '';
        items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-item';
            div.innerHTML = escapeHtml(item.content || JSON.stringify(item)) + '<div class="meta">' + escapeHtml(item.createdAt || '') + '</div>';
            container.appendChild(div);
        });
    } catch (e) {
        console.error('Failed to load history:', e);
    }
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

let hasReceivedBackendTime = false;
function initLocalTime() {
    const now = new Date();
    document.getElementById('clockDisplay').textContent = now.toLocaleTimeString('zh-CN', {hour12: false});
    document.getElementById('clockDate').textContent = now.toLocaleDateString('zh-CN');
}
initLocalTime();

class SimulationWS {
    constructor() {
        this.ws = null;
        this.reconnectDelay = 1000;
    }
    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/ws/sim`);
        this.ws.onmessage = (e) => {
            try {
                this._onMessage(JSON.parse(e.data));
            } catch (err) {
                console.error('Failed to parse WS message:', err);
            }
        };
        this.ws.onclose = () => { setTimeout(() => this.connect(), this.reconnectDelay); };
        this.ws.onerror = () => this.ws.close();
    }
    send(msg) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    }
    _onMessage(msg) {
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
        } else if (msg.type === 'context_snapshot') {
        }
    }
}

class NotifyWS {
    constructor() {
        this.ws = null;
    }
    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/ws/notify`);
        this.ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'proactive_reminder') showNotification(msg);
            } catch (err) {
                console.error('Failed to parse notify message:', err);
            }
        };
        this.ws.onclose = () => { setTimeout(() => this.connect(), 2000); };
        this.ws.onerror = () => this.ws.close();
    }
}

const simWS = new SimulationWS();
const notifyWS = new NotifyWS();

function setSimClock() {
    const date = document.getElementById('simDate').value;
    const time = document.getElementById('simTime').value;
    if (!date && !time) return;
    const dt = date && time ? `${date}T${time}` : null;
    simWS.send({ type: 'set_clock', datetime: dt });
}

function setScale(scale, btn) {
    simWS.send({ type: 'set_time_scale', scale });
    document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function advanceClock(seconds) { simWS.send({ type: 'advance', seconds }); }

function resetClock() {
    simWS.send({ type: 'set_clock', datetime: null });
    document.getElementById('simDate').value = '';
    document.getElementById('simTime').value = '';
}

const FIELD_TO_INPUT = {
    'spatial.current_location.latitude': 'ctx-lat',
    'spatial.current_location.longitude': 'ctx-lng',
    'spatial.current_location.speed_kmh': 'ctx-speedKmh',
    'spatial.eta_minutes': 'ctx-etaMinutes',
    'traffic.estimated_delay_minutes': 'ctx-delayMinutes',
    'driver.fatigue_level': 'ctx-fatigueLevel',
};

function adjustField(field, delta) {
    const input = document.getElementById(FIELD_TO_INPUT[field]);
    if (!input) return;
    const step = parseFloat(input.step) || 1;
    input.value = (parseFloat(input.value) || 0) + delta * step;
    syncField(field, input.value);
}

function syncField(field, value) {
    simWS.send({ type: 'update_context', field, value: parseFloat(value) || value });
}

function showNotification(msg) {
    const area = document.getElementById('notificationArea');
    area.style.display = 'block';
    document.getElementById('notificationContent').innerHTML =
        `<strong>\u4e3b\u52a8\u63d0\u9192</strong>: ${escapeHtml(msg.content)} <div style="font-size:11px;color:#999;margin-top:4px">${escapeHtml(msg.triggered_at || '')}</div>`;
    const history = document.getElementById('notificationHistory');
    const item = document.createElement('div');
    item.className = 'notification-item';
    item.textContent = `${msg.content} (${msg.triggered_at || ''})`;
    history.prepend(item);
}

function dismissNotification() {
    document.getElementById('notificationArea').style.display = 'none';
}

let schedulerRunning = false;
function toggleScheduler() {
    schedulerRunning = !schedulerRunning;
    simWS.send({ type: schedulerRunning ? 'start_scheduler' : 'stop_scheduler' });
    const btn = document.getElementById('schedulerBtn');
    btn.textContent = schedulerRunning ? '\u505c\u6b62\u8c03\u5ea6' : '\u542f\u52a8\u8c03\u5ea6';
    btn.classList.toggle('btn-success', !schedulerRunning);
    btn.classList.toggle('btn-danger', schedulerRunning);
}

simWS.connect();
notifyWS.connect();

document.getElementById('ctx-emotion').value = 'neutral';
document.getElementById('ctx-workload').value = 'normal';
document.getElementById('ctx-fatigueLevel').value = '0';
document.getElementById('ctx-lat').value = '39.9042';
document.getElementById('ctx-lng').value = '116.4074';
document.getElementById('ctx-speedKmh').value = '0';
document.getElementById('ctx-congestionLevel').value = 'smooth';
document.getElementById('ctx-delayMinutes').value = '0';
document.getElementById('ctx-scenario').value = 'city_driving';

loadPresets();
loadHistory();
