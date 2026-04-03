# 测试页面三栏布局改造设计

**日期**: 2026-04-03
**状态**: 已批准

## 1. 概述

将现有测试页面从两栏布局改为三栏布局，移除预设配置和显式保存/启动逻辑，简化用户操作流程。

## 2. 布局设计

```
┌─────────────┬───────────────────┬─────────────────────┐
│   左侧面板   │    中间面板       │     右侧面板          │
│  (保持不变)  │  (新增文本输入)   │ (Agent状态+历史记录)  │
│  320px      │   flex: 1        │     flex: 1          │
└─────────────┴───────────────────┴─────────────────────┘
```

- **左侧面板 (320px)**: 保留时钟、上下文配置，移除预设相关UI
- **中间面板 (flex:1)**: 文本输入区，用于用户输入查询内容
- **右侧面板 (flex:1)**: Agent状态列表(Context/Task/Decision/Execution)和历史记录

## 3. 移除内容

### 3.1 HTML 移除项
- `场景预设` 区块 (`<div class="section-title">场景预设</div>` 及其内容)
- `记忆模式` 下拉选择框
- `保存预设` 按钮
- `启动调度` 按钮 (`schedulerBtn`)

### 3.2 JavaScript 移除项
- `loadPresets()` 函数
- `loadPreset()` 函数
- `savePreset()` 函数
- `presetSelect` 相关逻辑
- `memoryMode` 相关逻辑（保留变量定义但固定值）
- `schedulerRunning` 和 `toggleScheduler()` 函数
- 页面加载时的 `loadPresets()` 调用

### 3.3 后端移除项
- `saveScenarioPreset` mutation
- `deleteScenarioPreset` mutation
- `scenarioPresets` query
- `_preset_store()` 函数

## 4. 中间面板设计

### 4.1 HTML 结构
```html
<div class="panel-middle">
    <div class="section-title">内容输入</div>
    <textarea id="contentInput" placeholder="输入要处理的内容..."></textarea>
    <button class="btn btn-primary" onclick="sendContent()">发送</button>
</div>
```

### 4.2 CSS 样式
- `panel-middle`: flex布局，flex-direction: column，padding: 16px
- `textarea`: 高度约200px，可调整，font-size: 14px
- 发送按钮: 居中对齐

### 4.3 交互逻辑
1. 用户在左侧配置上下文信息
2. 用户在中间文本框输入内容
3. 点击发送或按 Enter 键触发 `sendContent()`
4. 调用 GraphQL `processQuery` mutation
5. 结果展示在右侧面板

## 5. 上下文配置保留项

左侧面板保留以下配置：
- 时钟面板（时间显示、设置、快进、重置）
- 时间缩放比例按钮
- 驾驶员状态（情绪、负荷、疲劳程度）
- 时空信息（纬度、经度、地址、车速、目的地、ETA）
- 交通状况（拥堵程度、事故信息、延误）
- 驾驶场景

## 6. GraphQL 变化

### 6.1 保留的 mutation
`processQuery` 保持不变，参数：
- `query`: 来自中间文本输入
- `context`: 来自左侧表单
- `memoryMode`: 固定为默认值 `MEMORY_BANK`

### 6.2 移除的 mutation
- `saveScenarioPreset`
- `deleteScenarioPreset`

### 6.3 移除的 query
- `scenarioPresets`

## 7. 文件变更清单

| 文件 | 变更类型 |
|------|----------|
| webui/index.html | 修改 |
| webui/app.js | 修改 |
| webui/styles.css | 修改 |
| app/api/resolvers/mutation.py | 修改 |
| app/api/resolvers/query.py | 修改 |
| app/api/graphql_schema.py | 修改 |

## 8. 实现步骤

1. 修改 `index.html`：
   - 添加 `panel-middle` div
   - 移除预设区块、记忆模式、启动调度按钮
   - 将右侧面板重构为Agent状态+历史记录

2. 修改 `styles.css`：
   - 添加 `.panel-middle` 样式
   - 移除 `.panel-right` 中不再需要的样式
   - 调整 `.main` 为三栏布局

3. 修改 `app.js`：
   - 实现 `sendContent()` 函数
   - 移除 `loadPresets()`, `savePreset()`, `loadPreset()`
   - 移除 `toggleScheduler()` 相关逻辑
   - 调整 `sendQuery()` 为 `sendContent()`

4. 修改后端 GraphQL：
   - 移除 preset 相关 mutation 和 query
   - 保持 `processQuery` 不变
