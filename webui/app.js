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
        const sel = document.getElementById('presetSelect');
        sel.innerHTML = '<option value="">⚠ 预设加载失败</option>';
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

let _experimentChart = null;

async function loadExperimentData() {
    try {
        const data = await graphql(
            `query { experimentResults { strategies { strategy exact_match field_f1 value_f1 } } }`
        );
        const strats = data.experimentResults.strategies;
        const labels = strats.map(s => s.strategy);
        const exact = strats.map(s => s.exact_match);
        const field = strats.map(s => s.field_f1);
        const value = strats.map(s => s.value_f1);

        const ctx = document.getElementById('experimentChart').getContext('2d');
        if (_experimentChart) _experimentChart.destroy();
        _experimentChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    { label: 'Exact Match', data: exact, backgroundColor: '#4285F4' },
                    { label: 'Field F1', data: field, backgroundColor: '#34A853' },
                    { label: 'Value F1', data: value, backgroundColor: '#FBBC05' },
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: '五策略对比' },
                }
            }
        });
    } catch (e) {
        console.error('Failed to load experiment data:', e);
        const canvas = document.getElementById('experimentChart');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.font = '14px sans-serif';
            ctx.fillStyle = '#999';
            ctx.textAlign = 'center';
            ctx.fillText('实验数据加载失败，请检查 experiment_benchmark.toml', canvas.width / 2, canvas.height / 2);
        }
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
                history(limit: $limit, memoryMode: $memoryMode) { id content type description createdAt }
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
            let html = '';
            if (item.type) html += '<span class="type-tag">' + escapeHtml(item.type) + '</span> ';
            html += escapeHtml(item.content || JSON.stringify(item));
            if (item.description) html += '<div class="meta">' + escapeHtml(item.description) + '</div>';
            html += '<div class="meta">' + escapeHtml(item.createdAt || '') + '</div>';
            div.innerHTML = html;
            container.appendChild(div);
        });
    } catch (e) {
        console.error('Failed to load history:', e);
        const container = document.getElementById('historyList');
        container.innerHTML = '<span class="error">加载历史失败</span>';
    }
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

loadPresets();
loadHistory();
