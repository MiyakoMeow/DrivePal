let currentEventId = null;

async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

function getContextInput() {
    const emotion = document.getElementById('ctx-emotion').value;
    const workload = document.getElementById('ctx-workload').value;
    const fatigue_level = parseFloat(document.getElementById('ctx-fatigueLevel').value);
    const lat = document.getElementById('ctx-lat').value;
    const lng = document.getElementById('ctx-lng').value;
    const address = document.getElementById('ctx-address').value;
    const speed_kmh = document.getElementById('ctx-speedKmh').value;
    const destAddress = document.getElementById('ctx-dest-address').value;
    const eta_minutes = document.getElementById('ctx-etaMinutes').value;
    const congestion_level = document.getElementById('ctx-congestionLevel').value;
    const incidents = document.getElementById('ctx-incidents').value;
    const delay_minutes = document.getElementById('ctx-delayMinutes').value;
    const scenario = document.getElementById('ctx-scenario').value;

    const driver = {};
    if (emotion) driver.emotion = emotion;
    if (workload) driver.workload = workload;
    driver.fatigue_level = fatigue_level;

    const spatial = {};
    const curLoc = {};
    if (lat !== '') curLoc.latitude = parseFloat(lat);
    if (lng !== '') curLoc.longitude = parseFloat(lng);
    if (address) curLoc.address = address;
    if (speed_kmh !== '') curLoc.speed_kmh = parseFloat(speed_kmh);
    if (Object.keys(curLoc).length) spatial.current_location = curLoc;

    const dest = {};
    if (destAddress) dest.address = destAddress;
    if (Object.keys(dest).length) spatial.destination = dest;

    if (eta_minutes !== '') spatial.eta_minutes = parseFloat(eta_minutes);

    const traffic = {};
    if (congestion_level) traffic.congestion_level = congestion_level;
    if (incidents) traffic.incidents = incidents.split(',').map(s => s.trim()).filter(Boolean);
    if (delay_minutes !== '') traffic.estimated_delay_minutes = parseInt(delay_minutes, 10);

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
    document.getElementById('ctx-fatigueLevel').value = d.fatigue_level ?? 0;
    document.getElementById('fatigueVal').textContent = (d.fatigue_level ?? 0).toFixed(1);

    const cl = s.current_location || {};
    document.getElementById('ctx-lat').value = cl.latitude ?? '';
    document.getElementById('ctx-lng').value = cl.longitude ?? '';
    document.getElementById('ctx-address').value = cl.address || '';
    document.getElementById('ctx-speedKmh').value = cl.speed_kmh ?? '';

    const dest = s.destination || {};
    document.getElementById('ctx-dest-address').value = dest.address || '';
    document.getElementById('ctx-etaMinutes').value = s.eta_minutes ?? '';

    document.getElementById('ctx-congestionLevel').value = t.congestion_level || '';
    document.getElementById('ctx-incidents').value = Array.isArray(t.incidents) ? t.incidents.join(', ') : (t.incidents || '');
    document.getElementById('ctx-delayMinutes').value = t.estimated_delay_minutes ?? '';

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
        const presets = await api('GET', '/api/presets');
        const sel = document.getElementById('presetSelect');
        sel.innerHTML = '<option value="">-- 选择预设 --</option>';
        (presets || []).forEach(p => {
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
        await api('POST', '/api/presets', { name, context });
        alert('预设已保存');
        loadPresets();
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}

let _experimentChart = null;

async function loadExperimentData() {
    try {
        const data = await api('GET', '/api/experiments');
        const strats = data.strategies;
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

function handleSSEEvent(event, data) {
    switch (event) {
        case 'stage_start': {
            const stage = data.stage;
            if (stage === 'joint_decision') {
                document.getElementById('stage-task-body').innerHTML =
                    '<span class="empty-hint">处理中...</span>';
                document.getElementById('stage-decision-body').innerHTML =
                    '<span class="empty-hint">处理中...</span>';
            } else {
                document.getElementById(`stage-${stage}-body`).innerHTML =
                    '<span class="empty-hint">处理中...</span>';
            }
            break;
        }
        case 'context_done':
            document.getElementById('stage-context-body').textContent = formatJson(data.context);
            break;
        case 'decision':
            document.getElementById('stage-task-body').textContent = formatJson({ task_type: data.task_type });
            document.getElementById('stage-decision-body').textContent = formatJson(data);
            break;
        case 'done':
            if (data.event_id) {
                currentEventId = data.event_id;
                document.getElementById('feedbackRow').style.display = 'flex';
            }
            if (data.status === 'pending') {
                document.getElementById('stage-execution-body').textContent =
                    '提醒已延迟: ' + (data.pending_reminder_id ? 'ID ' + data.pending_reminder_id : data.status);
            } else if (data.result) {
                document.getElementById('stage-execution-body').textContent = formatJson(data.result);
            } else if (data.reason) {
                document.getElementById('stage-execution-body').textContent = data.reason;
            }
            break;
        case 'error':
            ['context', 'task', 'decision', 'execution'].forEach(s => {
                const el = document.getElementById(`stage-${s}-body`);
                if (el.querySelector('.empty-hint')) {
                    el.innerHTML = '<span class="error">' + escapeHtml(data.message ?? '未知错误') + '</span>';
                }
            });
            break;
    }
}

async function sendQuery() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query) return;

    const context = getContextInput();

    setLoading(true);
    document.getElementById('feedbackRow').style.display = 'none';
    ['context', 'task', 'decision', 'execution'].forEach(s => {
        document.getElementById(`stage-${s}-body`).innerHTML = '<span class="empty-hint">处理中...</span>';
    });

    try {
        const body = { query };
        if (context) body.context = context;

        const resp = await fetch('/api/query/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let currentEvent = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    currentEvent = line.slice(7).trim();
                } else if (line.startsWith('data: ') && currentEvent) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleSSEEvent(currentEvent, data);
                    } catch (e) {
                        console.error('Failed to parse SSE data:', e);
                    }
                    currentEvent = '';
                }
            }
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
        await api('POST', '/api/feedback', { event_id: currentEventId, action });
        document.getElementById('feedbackRow').style.display = 'none';
    } catch (e) {
        alert('反馈提交失败: ' + e.message);
    }
}

async function loadHistory() {
    try {
        const items = await api('GET', '/api/history?limit=10');
        const container = document.getElementById('historyList');
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
            html += '<div class="meta">' + escapeHtml(item.created_at || '') + '</div>';
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
