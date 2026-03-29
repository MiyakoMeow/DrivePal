import re
from app.memory.schemas import MemoryEvent


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    if not history_text.strip():
        return []
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+(.+)$")
    records = []
    for i, line in enumerate(history_text.strip().splitlines()):
        m = pattern.match(line)
        if m:
            date_group = m.group(1)
            content = m.group(2)
        else:
            date_group = "unknown"
            content = line
        records.append(
            MemoryEvent(
                id=f"hist_{i}",
                content=content,
                description=content,
                type="general",
                date_group=date_group,
                memory_strength=1,
            )
        )
    return records


def format_search_results(results) -> tuple[str, int]:
    if not results:
        return ("", 0)
    texts = []
    for r in results:
        event = r.event if hasattr(r, "event") else r
        if isinstance(event, dict):
            content = event.get("content", "")
        elif hasattr(event, "content"):
            content = event.content
        else:
            content = str(event)
        if content:
            texts.append(content)
    return ("\n".join(texts), len(texts))


class StoreClient:
    def __init__(self, store):
        self.store = store

    def search(self, query, user_id=None, top_k=5):
        return self.store.search(query=query, top_k=top_k)
