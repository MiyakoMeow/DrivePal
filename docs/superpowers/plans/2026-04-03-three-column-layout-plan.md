# 测试页面三栏布局实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将测试页面从两栏布局改为三栏布局，移除预设配置相关功能

**Architecture:** 
- 前端采用三栏布局：左侧(上下文配置) + 中间(文本输入) + 右侧(Agent状态+历史)
- 后端移除 scenario_presets 相关 GraphQL API
- 交互保持发送按钮/回车触发

**Tech Stack:** FastAPI, Strawberry GraphQL, Vanilla JS, HTML/CSS

---

## 文件变更清单

| 文件 | 变更类型 |
|------|----------|
| webui/index.html | 修改 |
| webui/styles.css | 修改 |
| webui/app.js | 修改 |
| app/api/graphql_schema.py | 修改 |
| app/api/resolvers/mutation.py | 修改 |
| app/api/resolvers/query.py | 修改 |

---

## Task 1: 修改 webui/index.html - 三栏布局

**Files:**
- Modify: `webui/index.html:1-230`

- [ ] **Step 1: 读取当前 index.html**

```bash
cat webui/index.html
```

- [ ] **Step 2: 重写 index.html 为三栏布局**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>知行车秘 — 模拟测试工作台</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <div class="header">
        <span>知行车秘 — 模拟测试工作台</span>
        <a href="/graphql" target="_blank">GraphQL Playground</a>
    </div>

    <div class="main">
        <!-- 左侧面板: 上下文配置 -->
        <div class="panel-left">
            <div class="clock-panel">
                <div class="clock-display" id="clockDisplay"></div>
                <div class="clock-date" id="clockDate"></div>
                <div class="clock-controls">
                    <input type="date" id="simDate">
                    <input type="time" id="simTime" step="1">
                    <button class="btn btn-primary btn-xs" onclick="setSimClock()">设置</button>
                </div>
                <div class="scale-btn-group">
                    <button class="scale-btn active" onclick="setScale(1, this)">1x</button>
                    <button class="scale-btn" onclick="setScale(2, this)">2x</button>
                    <button class="scale-btn" onclick="setScale(5, this)">5x</button>
                    <button class="scale-btn" onclick="setScale(10, this)">10x</button>
                    <button class="scale-btn" onclick="setScale(60, this)">60x</button>
                </div>
                <div class="clock-actions">
                    <button class="btn btn-secondary btn-xs" onclick="advanceClock(3600)">快进 1h</button>
                    <button class="btn btn-secondary btn-xs" onclick="resetClock()">重置</button>
                </div>
            </div>

            <div>
                <div class="section-title">驾驶员状态</div>
                <div class="field">
                    <label>情绪</label>
                    <select id="ctx-emotion">
                        <option value="">（未设置）</option>
                        <option value="neutral">正常</option>
                        <option value="calm">平静</option>
                        <option value="anxious">焦虑</option>
                        <option value="fatigued">疲倦</option>
                        <option value="angry">愤怒</option>
                    </select>
                </div>
                <div class="field">
                    <label>负荷</label>
                    <select id="ctx-workload">
                        <option value="">（未设置）</option>
                        <option value="low">低</option>
                        <option value="normal">正常</option>
                        <option value="high">高</option>
                        <option value="overloaded">过载</option>
                    </select>
                </div>
                <div class="field">
                    <label>疲劳程度: <span id="fatigueVal" class="range-val">0.0</span></label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('driver.fatigue_level', -0.1)">−</button>
                        <input type="number" id="ctx-fatigueLevel" min="0" max="1" step="0.1" value="0" oninput="syncField('driver.fatigue_level', this.value); document.getElementById('fatigueVal').textContent=parseFloat(this.value).toFixed(1)">
                        <button class="spin-btn" onclick="adjustField('driver.fatigue_level', 0.1)">+</button>
                    </div>
                </div>
            </div>

            <div>
                <div class="section-title">时空信息</div>
                <div class="field">
                    <label>纬度</label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.latitude', -0.001)">−</button>
                        <input type="number" id="ctx-lat" step="0.001" value="0" placeholder="例: 39.9042" oninput="syncField('spatial.current_location.latitude', this.value)">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.latitude', 0.001)">+</button>
                    </div>
                </div>
                <div class="field">
                    <label>经度</label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.longitude', -0.001)">−</button>
                        <input type="number" id="ctx-lng" step="0.001" value="0" placeholder="例: 116.4074" oninput="syncField('spatial.current_location.longitude', this.value)">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.longitude', 0.001)">+</button>
                    </div>
                </div>
                <div class="field">
                    <label>地址</label>
                    <input type="text" id="ctx-address" placeholder="当前位置地址">
                </div>
                <div class="field">
                    <label>车速 (km/h)</label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', -5)">−</button>
                        <input type="number" id="ctx-speedKmh" step="5" value="0" min="0" oninput="syncField('spatial.current_location.speed_kmh', this.value)">
                        <button class="spin-btn" onclick="adjustField('spatial.current_location.speed_kmh', 5)">+</button>
                    </div>
                </div>
                <div class="field">
                    <label>目的地地址</label>
                    <input type="text" id="ctx-dest-address" placeholder="目的地">
                </div>
                <div class="field">
                    <label>ETA (分钟)</label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('spatial.eta_minutes', -1)">−</button>
                        <input type="number" id="ctx-etaMinutes" step="1" value="0" min="0" placeholder="预估到达时间" oninput="syncField('spatial.eta_minutes', this.value)">
                        <button class="spin-btn" onclick="adjustField('spatial.eta_minutes', 1)">+</button>
                    </div>
                </div>
            </div>

            <div>
                <div class="section-title">交通状况</div>
                <div class="field">
                    <label>拥堵程度</label>
                    <select id="ctx-congestionLevel">
                        <option value="">（未设置）</option>
                        <option value="smooth">畅通</option>
                        <option value="slow">缓行</option>
                        <option value="congested">拥堵</option>
                        <option value="blocked">严重拥堵</option>
                    </select>
                </div>
                <div class="field">
                    <label>事故信息</label>
                    <input type="text" id="ctx-incidents" placeholder="事故描述（可选）">
                </div>
                <div class="field">
                    <label>延误 (分钟)</label>
                    <div class="number-spinner">
                        <button class="spin-btn" onclick="adjustField('traffic.estimated_delay_minutes', -1)">−</button>
                        <input type="number" id="ctx-delayMinutes" step="1" value="0" min="0" oninput="syncField('traffic.estimated_delay_minutes', this.value)">
                        <button class="spin-btn" onclick="adjustField('traffic.estimated_delay_minutes', 1)">+</button>
                    </div>
                </div>
            </div>

            <div>
                <div class="section-title">驾驶场景</div>
                <div class="field">
                    <label>场景类型</label>
                    <select id="ctx-scenario">
                        <option value="">（未设置）</option>
                        <option value="parked">停车场</option>
                        <option value="city_driving">城市道路</option>
                        <option value="highway">高速公路</option>
                        <option value="traffic_jam">交通拥堵</option>
                    </select>
                </div>
            </div>

            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" onclick="clearForm()">清空表单</button>
            </div>
        </div>

        <!-- 中间面板: 文本输入 -->
        <div class="panel-middle">
            <div class="section-title">内容输入</div>
            <textarea id="contentInput" placeholder="输入要处理的内容..." onkeydown="if(event.key==='Enter' && event.ctrlKey) sendContent()"></textarea>
            <button class="btn btn-primary" id="sendBtn" onclick="sendContent()">发送</button>
        </div>

        <!-- 右侧面板: Agent状态+历史记录 -->
        <div class="panel-right">
            <div class="notification-area" id="notificationArea" style="display:none;">
                <div class="notification-banner" id="notificationBanner">
                    <div class="notification-content" id="notificationContent"></div>
                    <button class="notification-dismiss" onclick="dismissNotification()">&#x2715;</button>
                </div>
                <div class="notification-history" id="notificationHistory"></div>
            </div>

            <details class="stage" id="stage-context" open>
                <summary>Context Agent</summary>
                <div class="stage-body"><pre id="stage-context-body"><span class="empty-hint">等待查询...</span></pre></div>
            </details>

            <details class="stage" id="stage-task">
                <summary>Task Agent</summary>
                <div class="stage-body"><pre id="stage-task-body"><span class="empty-hint">等待查询...</span></pre></div>
            </details>

            <details class="stage" id="stage-decision">
                <summary>Strategy Agent</summary>
                <div class="stage-body"><pre id="stage-decision-body"><span class="empty-hint">等待查询...</span></pre></div>
            </details>

            <details class="stage" id="stage-execution">
                <summary>Execution Agent</summary>
                <div class="stage-body"><pre id="stage-execution-body"><span class="empty-hint">等待查询...</span></pre></div>
                <div class="feedback-row" id="feedbackRow" style="display:none; padding: 0 14px 12px;">
                    <button class="btn btn-success btn-sm" onclick="submitFeedback('accept')">接受</button>
                    <button class="btn btn-secondary btn-sm" onclick="submitFeedback('ignore')">忽略</button>
                </div>
            </details>

            <div class="card history-section">
                <div class="section-title">历史记录</div>
                <div id="historyList"><span class="empty-hint">暂无历史记录</span></div>
            </div>
        </div>
    </div>

    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: 验证文件写入成功**

---

## Task 2: 修改 webui/styles.css - 添加 panel-middle 样式

**Files:**
- Modify: `webui/styles.css`

- [ ] **Step 1: 读取当前 styles.css**

- [ ] **Step 2: 添加 panel-middle 样式**

在 `.panel-right` 样式后添加:

```css
.panel-middle {
    flex: 1;
    min-width: 300px;
    background: #fff;
    border-right: 1px solid #e0e0e0;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.panel-middle textarea {
    width: 100%;
    min-height: 200px;
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 5px;
    font-size: 14px;
    resize: vertical;
    outline: none;
    font-family: inherit;
}

.panel-middle textarea:focus {
    border-color: #007bff;
    box-shadow: 0 0 0 2px rgba(0,123,255,.15);
}

.panel-middle .btn {
    align-self: center;
    padding: 10px 40px;
}
```

- [ ] **Step 3: 调整 .main 为三栏布局**

修改 `.main` 样式:

```css
.main {
    flex: 1;
    display: flex;
    overflow: hidden;
}
```

确认 `.panel-left` 保持 320px 宽度（已在原 CSS 中定义，无需修改）。

- [ ] **Step 4: 调整 .panel-right 样式**

```css
.panel-right {
    flex: 1;
    min-width: 300px;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}
```

- [ ] **Step 5: 移除不再需要的样式**

删除 `.preset-row` 相关样式 (如果存在):

```css
.preset-row {
    display: flex;
    gap: 8px;
    align-items: center;
}
.preset-row select { flex: 1; }
```

---

## Task 3: 修改 webui/app.js - 实现 sendContent() 并清理代码

**Files:**
- Modify: `webui/app.js`

- [ ] **Step 1: 读取当前 app.js**

- [ ] **Step 2: 重写 sendQuery 为 sendContent**

将原来的 `sendQuery` 函数改为 `sendContent`:

```javascript
async function sendContent() {
    const content = document.getElementById('contentInput').value.trim();
    if (!content) return;

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
            { query: content, memoryMode: 'MEMORY_BANK', context }
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
```

- [ ] **Step 3: 移除 preset 相关函数**

删除以下函数:
- `loadPresets()`
- `loadPreset()`
- `savePreset()`

- [ ] **Step 4: 移除 memoryMode 动态值相关代码**

将:
```javascript
const memoryMode = document.getElementById('memoryMode').value;
```

改为固定值 `'MEMORY_BANK'` 或在 `sendContent` 中直接使用。

- [ ] **Step 5: 移除 toggleScheduler 相关代码**

删除:
- `schedulerRunning` 变量
- `toggleScheduler()` 函数
- `schedulerBtn` 相关调用

- [ ] **Step 6: 移除页面加载时的 preset 调用**

删除:
- `loadPresets()` 调用

- [ ] **Step 7: 移除 fillForm 和 clearForm 中的 preset 相关代码**

`clearForm` 保持不变即可，因为它只清理上下文表单字段。

---

## Task 4: 修改 app/api/resolvers/mutation.py - 移除 preset mutations

**Files:**
- Modify: `app/api/resolvers/mutation.py`

- [ ] **Step 1: 读取当前 mutation.py**

- [ ] **Step 2: 移除 _preset_store 函数**

删除:
```python
def _preset_store() -> TOMLStore:
    from app.api.main import DATA_DIR

    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)
```

- [ ] **Step 3: 移除 save_scenario_preset mutation**

删除整个 `@strawberry.mutation` 方法 `save_scenario_preset`

- [ ] **Step 4: 移除 delete_scenario_preset mutation**

删除整个 `@strawberry.mutation` 方法 `delete_scenario_preset`

- [ ] **Step 5: 清理导入**

移除不再使用的导入:
- `Path` (如果仅用于 preset)
- `ScenarioPreset` (如果仅用于 preset)

---

## Task 5: 修改 app/api/resolvers/query.py - 移除 scenario_presets query

**Files:**
- Modify: `app/api/resolvers/query.py`

- [ ] **Step 1: 读取当前 query.py**

- [ ] **Step 2: 移除 scenario_presets query**

删除:
```python
@strawberry.field
async def scenario_presets(self) -> list[ScenarioPresetGQL]:
    """查询所有场景预设."""
    from app.api.resolvers.mutation import _preset_store, _to_gql_preset

    store = _preset_store()
    presets = await store.read()
    return [_to_gql_preset(p) for p in presets]
```

- [ ] **Step 3: 清理导入**

移除 `ScenarioPresetGQL` 导入

---

## Task 6: 修改 app/api/graphql_schema.py - 移除 preset 相关类型

**Files:**
- Modify: `app/api/graphql_schema.py`

- [ ] **Step 1: 读取当前 graphql_schema.py**

- [ ] **Step 2: 移除 ScenarioPresetInput 类**

删除:
```python
@strawberry.input
class ScenarioPresetInput:
    """场景预设输入."""

    name: str
    context: DrivingContextInput
```

- [ ] **Step 3: 移除 ScenarioPresetGQL 类**

删除:
```python
@strawberry.type
class ScenarioPresetGQL:
    """场景预设."""

    id: str
    name: str
    context: DrivingContextGQL
    created_at: str
```

---

## Task 7: 运行检查

- [ ] **Step 1: 运行 ruff check**

```bash
uv run ruff check --fix
```

- [ ] **Step 2: 运行 ty check**

```bash
uv run ty check
```

- [ ] **Step 3: 运行 ruff format**

```bash
uv run ruff format
```

- [ ] **Step 4: 运行测试**

```bash
uv run pytest -v
```

---

## Task 8: 提交变更

- [ ] **Step 1: 提交所有变更**

```bash
git add -A && git commit -m "feat: refactor test page to three-column layout"
```
