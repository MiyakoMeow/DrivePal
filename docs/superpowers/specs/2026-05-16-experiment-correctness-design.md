# 实验正确性修复设计

## 背景

分析两个实验（消融实验 + VehicleMemBench 集成）后发现两个方法论缺陷，均位于 VehicleMemBench 适配器层。

## 修复项

### Fix #1：偏好关键词语言不匹配

**问题**：`_PREFERENCE_KEYWORDS` 仅含中文词（"设置"/"偏好"/...），VehicleMemBench 英文 benchmark 数据无法匹配，所有记忆统一 `memory_strength=3`，偏好相关记忆未获 strength=5 强化。

**影响**：drivepal 组与 none/summary/kv 对比时低估 MemoryBank 检索质量。

**方案**：新增 `_EN_PREFERENCE_KEYWORDS` 英文关键词集合（prefer/change/set/switch/turn on/turn off/adjust/want/like/would rather/choose/make it）。两套并查，任一匹配即 `strength=5`。

**变更范围**：仅 `adapter.py` 模块级常量 + `run_add` 中 `processor` 的 strength 判定逻辑。

### Fix #2：记忆创建时间丢原始时间戳

**问题**：`_async_add` 用 `datetime.now(UTC).isoformat()` 作为 `created_at`，所有记忆被视为同时创建。Ebbinghaus 遗忘曲线依赖时间差计算保留率，时间结构丢失后衰减效果被消弭。

**影响**：近期/远期事件检索权重无差异，MemoryBank 时序感知优势无法体现。

**方案**：
1. `DrivePalMemClient.add()` 新增 `created_at: str | None = None` 参数
2. `_async_add` 转发至 `MemoryEvent.created_at`（None 时默认 `datetime.now(UTC)`）
3. `run_add` 的 `processor` 从 `bucket.dt` 生成 ISO 时间字符串传入

**变更范围**：`DrivePalMemClient.add`、`_async_add`、`processor` 内部。

## 不修项

### Judge 中位数跨维度复合

`_median_scores` 三个维度各自排序取中位数后拼合为单条记录。该复合记录非任何真实 LLM 输出。改动需重新设计聚合逻辑且破坏现有统计链。实际影响极低——三个中位数大概率来自同一组 3 次评分中的中位那次。记录为已知局限。

## 测试

- 新增测试：英文偏好关键词匹配（含大小写）
- 新增测试：`created_at` 从 bucket.dt 正确注入
- 新增测试：`created_at=None` 时回退 `datetime.now()`
- 现有测试不应回归
