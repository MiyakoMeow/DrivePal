# 记忆库增强：软遗忘 + 人格摘要

## 背景

对标 [MemoryBank-SiliconFriend](https://github.com/zhongwanjun/MemoryBank-SiliconFriend) 实现，当前项目已实现遗忘曲线、记忆强化、每日摘要，但缺少：
1. **软遗忘机制**：原项目基于遗忘曲线随机删除记忆，当前项目只算 score 不执行遗忘
2. **人格分析摘要**：原项目包含 `personality` 每日分析 + `overall_personality` 整体画像

## 设计决策

- **软遗忘**：不下线数据，只将 `memory_strength` 大幅下调（0.1），使 retention score 极低自动沉底
- **人格摘要**：采用方案二，完全对齐原项目结构

---

## 1. 软遗忘机制

### 触发条件

- 每次 `search()` 时，对未匹配的事件计算 `retention = forgetting_curve(days_elapsed, strength)`
- 若 `retention < SOFT_FORGET_THRESHOLD`（默认 0.15）且非当天创建，触发软遗忘

### 遗忘行为

- `memory_strength` → `SOFT_FORGET_STRENGTH`（0.1）
- `forgotten = True`（标记位，方便后续扩展如"恢复记忆"）

### 实现位置

`app/memory/components.py` 的 `MemoryBankEngine`：

```python
SOFT_FORGET_THRESHOLD = 0.15
SOFT_FORGET_STRENGTH = 0.1

def _soft_forget_events(self, all_events: list[dict], matched_ids: set[str]) -> None:
    """对 retention 过低的记忆执行软遗忘"""
    today = datetime.now(timezone.utc).date()
    updated = False
    for event in all_events:
        if event.get("id") in matched_ids:
            continue
        strength = event.get("memory_strength", 1)
        last_recall = event.get("last_recall_date", today.isoformat())
        try:
            last_date = date.fromisoformat(last_recall)
            days_elapsed = (today - last_date).days
        except (ValueError, TypeError):
            days_elapsed = 0
        retention = forgetting_curve(days_elapsed, strength)
        if retention < SOFT_FORGET_THRESHOLD:
            event["memory_strength"] = SOFT_FORGET_STRENGTH
            event["forgotten"] = True
            updated = True
    if updated:
        self._storage.write_events(all_events)
```

在 `_strengthen_events` 末尾调用：

```python
def _strengthen_events(self, matched_events: list[dict]) -> None:
    # ... 现有强化逻辑 ...
    matched_ids = {e["id"] for e in matched_events if "id" in e}
    self._soft_forget_events(all_events, matched_ids)  # 新增
```

---

## 2. 人格摘要

### 存储结构

新建 `app/storage/json_store.py` 中的 `JSONStore` 实例，存储路径：`{data_dir}/memorybank_personality.json`

```json
{
  "daily_personality": {
    "2026-04-01": {
      "content": "用户性格分析内容...",
      "memory_strength": 1,
      "last_recall_date": "2026-04-01"
    }
  },
  "overall_personality": "用户整体人格档案..."
}
```

### LLM Prompt（参考原项目）

**每日人格分析** (`summarize_person_prompt`)：
```
Based on the following dialogue, please summarize {user_name}'s personality traits and emotions, 
and devise response strategies based on your speculation. Dialogue content:
{对话内容}

{user_name}'s personality traits, emotions, and {boot_name}'s response strategy are:
```

**整体人格汇总** (`summarize_overall_personality`)：
```
The following are the user's exhibited personality traits and emotions throughout multiple dialogues, 
along with appropriate response strategies for the current situation:
{每日人格分析内容}

Please provide a highly concise and general summary of the user's personality and the most appropriate 
response strategy for the AI lover, summarized as:
```

### 触发阈值

- `PERSONALITY_SUMMARY_THRESHOLD = 2`：每日对话数达到 2 时触发人格摘要
- `OVERALL_PERSONALITY_THRESHOLD = 3`：累计 3 条每日人格摘要时触发整体汇总

### 实现位置

`app/memory/components.py` 的 `MemoryBankEngine`：

```python
PERSONALITY_SUMMARY_THRESHOLD = 2
OVERALL_PERSONALITY_THRESHOLD = 3

def __init__(self, ...):
    # ... 现有初始化 ...
    self._personality_store = JSONStore(
        data_dir,
        Path("memorybank_personality.json"),
        lambda: {"daily_personality": {}, "overall_personality": ""},
    )

def _maybe_summarize_personality(self, date_group: str) -> None:
    """每日对话达到阈值时，生成人格分析摘要"""
    events = self._storage.read_events()
    group_events = [e for e in events if e.get("date_group") == date_group]
    count = len(group_events)
    if count < PERSONALITY_SUMMARY_THRESHOLD:
        return
    # ... 构建 prompt，调用 chat_model.generate() ...

def _update_overall_personality(self) -> None:
    """汇总多条每日人格分析为整体人格档案"""
    # ... 调用 chat_model.generate() ...
```

---

## 3. 搜索时人格摘要参与检索

在 `search()` 方法中，对齐原项目 `local_doc_qa.py` 的 `search_memory` 逻辑：

```python
def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
    # ... 现有 event + daily_summary 搜索 ...
    
    # 新增：人格摘要搜索（权重略低）
    personality_results = self._search_personality(query, top_k=1)
    all_results = event_results + summary_results + personality_results
    all_results.sort(key=lambda x: x.score, reverse=True)
    return all_results[:top_k]

def _search_personality(self, query: str, top_k: int) -> list[SearchResult]:
    """搜索人格摘要，retention 权重为 SUMMARY_WEIGHT * 0.8"""
    # ... 关键词匹配逻辑 ...
```

---

## 4. 数据流

```
write_interaction()
  → 写入 interactions.json
  → _maybe_summarize()          # 每日内容摘要
  → _maybe_summarize_personality()  # 每日人格摘要

search()
  → _search_by_embedding()      # 向量搜索
  → _strengthen_events()        # 强化匹配记忆
  → _soft_forget_events()       # 软遗忘低 retention 记忆
  → _search_summaries()        # 搜索每日摘要
  → _search_personality()       # 搜索人格摘要
```

---

## 5. 测试要点

1. **软遗忘触发**：`memory_strength` 在 retention < 0.15 时降至 0.1
2. **人格摘要生成**：每日对话数≥2 时生成人格分析
3. **整体人格汇总**：累计 3 条每日人格后生成整体档案
4. **人格摘要参与检索**：搜索时人格摘要以正确权重返回
