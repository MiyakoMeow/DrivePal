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

async def _soft_forget_events(self, all_events: list[dict], matched_ids: set[str]) -> None:
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
        await self._storage.write_events(all_events)
```

在 `_strengthen_events` 末尾调用：

```python
async def _strengthen_events(self, matched_events: list[dict]) -> None:
    # ... 现有强化逻辑 ...
    matched_ids = {e["id"] for e in matched_events if "id" in e}
    all_events = await self._storage.read_events()
    await self._soft_forget_events(all_events, matched_ids)  # 新增
```

**注意**：`forgotten` 标记用于后续扩展"恢复记忆"功能，当前仅作标记。

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

async def _maybe_summarize_personality(self, date_group: str) -> None:
    """每日对话达到阈值时，生成人格分析摘要"""
    if not self.chat_model:
        return
    events = await self._storage.read_events()
    group_events = [e for e in events if e.get("date_group") == date_group]
    count = len(group_events)
    if count < PERSONALITY_SUMMARY_THRESHOLD:
        return
    personality_data = await self._personality_store.read()
    daily_personality = personality_data.get("daily_personality", {})
    if date_group in daily_personality:
        return
    interactions = await self._interactions_store.read()
    group_interactions = [
        i for i in interactions if i.get("event_id") in {e.get("id") for e in group_events}
    ]
    if len(group_interactions) < PERSONALITY_SUMMARY_THRESHOLD:
        return
    combined = "\n".join(
        f"用户: {i['query']}\n系统: {i['response']}" for i in group_interactions
    )
    prompt = f"""Based on the following dialogue, please summarize user's personality traits and emotions, 
and devise response strategies based on your speculation. Dialogue content:
{combined}

User's personality traits, emotions, and response strategy are:
"""
    try:
        summary_text = await self.chat_model.generate(prompt)
    except Exception:
        return
    daily_personality[date_group] = {
        "content": summary_text,
        "memory_strength": 1,
        "last_recall_date": date_group,
    }
    personality_data["daily_personality"] = daily_personality
    await self._personality_store.write(personality_data)
    if len(daily_personality) >= OVERALL_PERSONALITY_THRESHOLD:
        await self._update_overall_personality(personality_data)

async def _update_overall_personality(self, personality_data: dict) -> None:
    """汇总多条每日人格分析为整体人格档案"""
    if not self.chat_model:
        return
    daily_personality = personality_data.get("daily_personality", {})
    all_summaries = [
        f"[{date_group}] {data.get('content', '')}"
        for date_group, data in daily_personality.items()
        if isinstance(data, dict)
    ]
    combined = "\n".join(all_summaries)
    prompt = f"""The following are the user's exhibited personality traits and emotions throughout multiple dialogues, 
along with appropriate response strategies for the current situation:
{combined}

Please provide a highly concise and general summary of the user's personality and the most appropriate 
response strategy for the AI lover, summarized as:
"""
    try:
        overall = await self.chat_model.generate(prompt)
    except Exception:
        return
    personality_data["overall_personality"] = overall
    await self._personality_store.write(personality_data)
```

**chat_model 获取方式**：通过 `__init__` 参数注入 `chat_model: Optional[ChatModel] = None`，与现有 `_maybe_summarize` 保持一致。

---

## 3. 搜索时人格摘要参与检索

在 `search()` 方法中，对齐原项目 `local_doc_qa.py` 的 `search_memory` 逻辑：

```python
async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
    # ... 现有 event + daily_summary 搜索 ...
    
    # 新增：人格摘要搜索（权重略低）
    personality_results = await self._search_personality(query, top_k=1)
    all_results = event_results + summary_results + personality_results
    all_results.sort(key=lambda x: x.score, reverse=True)
    return all_results[:top_k]

async def _search_personality(self, query: str, top_k: int) -> list[SearchResult]:
    """搜索人格摘要，使用关键词匹配，retention 权重为 SUMMARY_WEIGHT * 0.8"""
    personality_data = await self._personality_store.read()
    daily_personality = personality_data.get("daily_personality", {})
    if not daily_personality:
        return []
    query_lower = query.lower()
    today = datetime.now(timezone.utc).date()
    results = []
    for date_group, data in daily_personality.items():
        if not isinstance(data, dict):
            continue
        content = data.get("content", "")
        if query_lower in content.lower():
            strength = data.get("memory_strength", 1)
            last_recall = data.get("last_recall_date", date_group)
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except (ValueError, TypeError):
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            score = retention * SUMMARY_WEIGHT * 0.8
            results.append(
                SearchResult(
                    event={
                        "content": content,
                        "date_group": date_group,
                        "memory_strength": strength,
                        "last_recall_date": last_recall,
                    },
                    score=score,
                    source="personality",
                )
            )
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_k]
```

---

## 4. 数据流

```
write_interaction()
  → 写入 interactions.json
  → _maybe_summarize(today)      # 每日内容摘要
  → _maybe_summarize_personality(today)  # 每日人格摘要

search()
  → _search_by_embedding()      # 向量搜索
  → _strengthen_events()        # 强化匹配记忆
  → _soft_forget_events()       # 软遗忘低 retention 记忆
  → _search_summaries()        # 搜索每日摘要
  → _search_personality()       # 搜索人格摘要
```

**人格摘要存储**：`{data_dir}/memorybank_personality.json`，使用 JSONStore 异步接口。

---

## 5. 测试要点

1. **软遗忘触发**：`memory_strength` 在 retention < 0.15 时降至 0.1
2. **人格摘要生成**：每日对话数≥2 时生成人格分析
3. **整体人格汇总**：累计 3 条每日人格后生成整体档案
4. **人格摘要参与检索**：搜索时人格摘要以正确权重返回
