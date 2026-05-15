class AppState {
    #currentEventId = null;
    #experimentChart = null;
    #ws = null;
    #wsReconnectTimer = null;
    #pendingQuery = null;
    #reconnectAttempts = 0;

    getCurrentEventId() { return this.#currentEventId; }
    setCurrentEventId(id) { this.#currentEventId = id; }
    setChart(chart) { this.#experimentChart = chart; }
    getChart() { return this.#experimentChart; }
    destroyChart() {
        if (this.#experimentChart) {
            this.#experimentChart.destroy();
            this.#experimentChart = null;
        }
    }
    setWs(ws) { this.#ws = ws; }
    getWs() { return this.#ws; }

    getReconnectAttempts() { return this.#reconnectAttempts; }
    resetReconnectAttempts() { this.#reconnectAttempts = 0; }
    incrementReconnectAttempts() { this.#reconnectAttempts += 1; }

    getWsReconnectTimer() { return this.#wsReconnectTimer; }
    setWsReconnectTimer(timer) { this.#wsReconnectTimer = timer; }

    getPendingQuery() { return this.#pendingQuery; }
    setPendingQuery(q) { this.#pendingQuery = q; }

    reset() {
        this.#currentEventId = null;
        this.#pendingQuery = null;
        document.getElementById('feedbackRow').style.display = 'none';
        ['context', 'task', 'decision', 'execution'].forEach(s => {
            document.getElementById(`stage-${s}-body`).innerHTML =
                '<span class="empty-hint">等待查询...</span>';
        });
    }

    destroy() {
        if (this.#ws) { this.#ws.close(); this.#ws = null; }
        this.destroyChart();
        if (this.#wsReconnectTimer) { clearTimeout(this.#wsReconnectTimer); }
    }
}

const state = new AppState();

async function api(method, path, body) {
    const opts = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-User-Id': 'default',
        },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error?.message || err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

function buildContext(rootEl) {
    const ctx = {};
    rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
        const path = el.dataset.ctxPath.split('.');
        let val = el.value;
        if (el.type === 'number' || el.type === 'range') {
            val = parseFloat(val);
            if (isNaN(val)) return;
        }
        if (val === '' || val === null || val === undefined) return;
        if (el.id === 'ctx-incidents') {
            val = val.split(',').map(s => s.trim()).filter(Boolean);
            if (val.length === 0) return;
        }
        let cur = ctx;
        for (let i = 0; i < path.length - 1; i++) {
            cur[path[i]] = cur[path[i]] || {};
            cur = cur[path[i]];
        }
        cur[path[path.length - 1]] = val;
    });
    return Object.keys(ctx).length ? ctx : null;
}

function fillContext(rootEl, ctx) {
    rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
        const path = el.dataset.ctxPath.split('.');
        let val = ctx;
        for (const key of path) {
            if (val == null) break;
            val = val[key];
        }
        if (val != null) {
            el.value = Array.isArray(val) ? val.join(', ') : val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });
}

function resetContext(rootEl) {
    rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
        if (el.type === 'range') { el.value = 0; }
        else { el.value = ''; }
        el.dispatchEvent(new Event('input', { bubbles: true }));
    });
}

function connectWS() {
    const existing = state.getWs();
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
        return existing;
    }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/api/v1/ws?user_id=default`;
    const ws = new WebSocket(wsUrl);
    state.setWs(ws);
    ws.onopen = () => {
        state.resetReconnectAttempts();
        const pending = state.getPendingQuery();
        if (pending) {
            state.setPendingQuery(null);
            ws.send(JSON.stringify(pending));
        }
    };
    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg.type, msg.payload);
        } catch (e) {
            console.warn('WS message handling failed:', e);
        }
    };
    ws.onclose = () => {
        state.setWs(null);
        setLoading(false);
        scheduleReconnect();
    };
    ws.onerror = () => { ws.close(); };
    return ws;
}

function scheduleReconnect() {
    const oldTimer = state.getWsReconnectTimer();
    if (oldTimer) clearTimeout(oldTimer);
    const existing = state.getWs();
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
        return;
    }
    const delay = Math.min(1000 * Math.pow(2, state.getReconnectAttempts()), 30000);
    state.incrementReconnectAttempts();
    const timer = setTimeout(() => connectWS(), delay);
    state.setWsReconnectTimer(timer);
}

function handleWSMessage(type, data) {
    switch (type) {
        case 'stage_start': {
            const stage = data.stage;
            if (stage === 'joint_decision') {
                document.getElementById('stage-task-body').innerHTML =
                    '<span class="empty-hint">处理中...</span>';
                document.getElementById('stage-decision-body').innerHTML =
                    '<span class="empty-hint">处理中...</span>';
            } else {
                const el = document.getElementById(`stage-${stage}-body`);
                if (el) {
                    el.innerHTML = '<span class="empty-hint">处理中...</span>';
                } else {
                    console.warn('Unknown stage:', stage);
                }
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
            setLoading(false);
            loadHistory();
            if (data.event_id) {
                state.setCurrentEventId(data.event_id);
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
            setLoading(false);
            showToast(data.message ?? '未知错误', 'error');
            ['context', 'task', 'decision', 'execution'].forEach(s => {
                const el = document.getElementById(`stage-${s}-body`);
                if (el.querySelector('.empty-hint')) {
                    el.innerHTML = '<span class="error">' + escapeHtml(data.message ?? '未知错误') + '</span>';
                }
            });
            break;
        case 'reminder':
            showToast('收到提醒: ' + (data.message || '请查看执行结果'), 'info');
            break;
    }
}

async function sendQuery() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query) return;
    const context = buildContext(document.querySelector('.panel-left'));
    const ws = state.getWs();
    const payload = { type: 'query', payload: { query, context, session_id: 'webui-' + Date.now() } };
    state.reset();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast('WebSocket 未连接，正在重连...', 'error');
        state.setPendingQuery(payload);
        connectWS();
        return;
    }
    setLoading(true);
    ws.send(JSON.stringify(payload));
}

function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(container);
    }
    const el = document.createElement('div');
    const bg = type === 'error' ? '#dc3545' : type === 'success' ? '#28a745' : '#007bff';
    el.style.cssText = `padding:10px 16px;border-radius:6px;color:#fff;font-size:13px;max-width:360px;word-wrap:break-word;background:${bg};box-shadow:0 2px 8px rgba(0,0,0,.15);`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transition = 'opacity .3s';
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

async function submitFeedback(action) {
    const eventId = state.getCurrentEventId();
    if (!eventId) return;
    const body = { event_id: eventId, action };
    if (action === 'modify') {
        const content = prompt('请输入修改后的内容:');
        if (!content) return;
        body.modified_content = content;
    }
    try {
        await api('POST', '/api/v1/feedback', body);
        document.getElementById('feedbackRow').style.display = 'none';
    } catch (e) {
        showToast('反馈提交失败: ' + e.message, 'error');
    }
}

function formatJson(val) {
    if (val === null || val === undefined) return 'null';
    try {
        return JSON.stringify(val, null, 2);
    } catch {
        return String(val);
    }
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function setLoading(on) {
    const btn = document.getElementById('sendBtn');
    btn.disabled = on;
    btn.innerHTML = on ? '<span class="spinner"></span>处理中...' : '发送';
}

async function loadPresets() {
    try {
        const presets = await api('GET', '/api/v1/presets');
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
    resetContext(document.querySelector('.panel-left'));
    fillContext(document.querySelector('.panel-left'), JSON.parse(opt.dataset.preset).context);
}

async function savePreset() {
    const name = prompt('请输入预设名称:');
    if (!name) return;
    const context = buildContext(document.querySelector('.panel-left'));
    if (!context) { alert('请至少填写一项上下文信息'); return; }
    try {
        await api('POST', '/api/v1/presets', { name, context });
        showToast('预设已保存', 'success');
        loadPresets();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function loadExperimentData() {
    try {
        const data = await api('GET', '/api/v1/experiments');
        const strats = data.strategies;
        const labels = strats.map(s => s.strategy);
        const exact = strats.map(s => s.exact_match);
        const field = strats.map(s => s.field_f1);
        const value = strats.map(s => s.value_f1);

        const ctx = document.getElementById('experimentChart').getContext('2d');
        state.destroyChart();
        state.setChart(new Chart(ctx, {
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
        }));
    } catch (e) {
        showToast('实验数据加载失败', 'error');
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

async function loadHistory() {
    try {
        const items = await api('GET', '/api/v1/history?limit=10');
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
        showToast('加载历史失败: ' + e.message, 'error');
        const container = document.getElementById('historyList');
        container.innerHTML = '<span class="error">加载历史失败</span>';
    }
}

loadPresets();
loadHistory();
loadExperimentData();
connectWS();

setInterval(() => {
    const ws = state.getWs();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
}, 30000);
