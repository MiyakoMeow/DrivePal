"""PrepareRunner：加载数据集、划分预热/测试集、写入记忆库."""

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from app.experiment.loaders import get_test_cases
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.models.settings import get_chat_model

logger = logging.getLogger(__name__)

BACKEND_MODES = [
    MemoryMode.KEYWORD,
    MemoryMode.LLM_ONLY,
    MemoryMode.EMBEDDINGS,
    MemoryMode.MEMORY_BANK,
]

_SYSTEM_PROMPT = (
    "你是一个车载日程助手。用户会给你一条日程相关的指令，"
    "请用1-2句话给出简短的日程安排确认回复。"
)


def _load_dataset(name: str) -> list[dict[str, Any]]:
    return get_test_cases(name)


def _init_store_files(store_dir: Path) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "events.json").write_text("[]", encoding="utf-8")
    (store_dir / "strategies.json").write_text("{}", encoding="utf-8")


def _warmup_stores(
    warmup_items: dict[str, list[dict[str, Any]]],
    stores_dir: Path,
    chat_model: Any,
) -> None:
    for mode in BACKEND_MODES:
        mode_dir = stores_dir / mode.value
        _init_store_files(mode_dir)
        mem = MemoryModule(data_dir=str(mode_dir), chat_model=chat_model)
        mem.set_default_mode(mode)
        for _dataset_name, items in warmup_items.items():
            for item in items:
                response = item.get("response") or chat_model.generate(
                    item["input"], system_prompt=_SYSTEM_PROMPT,
                )
                mem.write_interaction(item["input"], response)


def prepare(
    base_dir: str = "data",
    datasets: list[str] | None = None,
    test_count: int = 50,
    warmup_ratio: float = 0.7,
    seed: int = 42,
) -> dict[str, Any]:
    """执行 Prepare 阶段：加载数据集、划分、预热记忆库."""
    if datasets is None:
        datasets = ["sgd_calendar", "scheduler"]

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(base_dir) / "exp" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    chat_model = get_chat_model()

    rng = random.Random(seed)

    dataset_stats: dict[str, dict[str, int]] = {}
    all_test_cases: list[dict[str, Any]] = []
    warmup_items: dict[str, list[dict[str, Any]]] = {}
    warmup_files: dict[str, str] = {}

    for ds_name in datasets:
        raw = _load_dataset(ds_name)
        if not raw:
            continue

        rng.shuffle(raw)

        total = min(
            len(raw),
            test_count + max(1, int(test_count * warmup_ratio / (1 - warmup_ratio))),
        )
        warmup_n = min(int(total * warmup_ratio), len(raw))
        test_n = min(total - warmup_n, len(raw) - warmup_n)

        warmup = raw[:warmup_n]
        test = raw[warmup_n : warmup_n + test_n]

        for item in warmup:
            response = chat_model.generate(item["input"], system_prompt=_SYSTEM_PROMPT)
            item["response"] = response

        dataset_stats[ds_name] = {"warmup_count": warmup_n, "test_count": len(test)}

        for tc in test:
            all_test_cases.append(
                {
                    "id": tc["id"],
                    "input": tc["input"],
                    "type": tc["type"],
                    "dataset": ds_name,
                },
            )

        warmup_items[ds_name] = warmup

    warmup_dir = run_dir / "warmup"
    warmup_dir.mkdir(parents=True, exist_ok=True)
    for ds_name, items in warmup_items.items():
        warmup_path = warmup_dir / f"{ds_name}.json"
        warmup_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        warmup_files[ds_name] = f"warmup/{ds_name}.json"

    stores_dir = run_dir / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    _warmup_stores(warmup_items, stores_dir, chat_model)

    result: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "warmup_ratio": warmup_ratio,
        "datasets": dataset_stats,
        "test_cases": all_test_cases,
        "warmup_files": warmup_files,
    }

    prepared_path = run_dir / "prepared.json"
    prepared_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    return result
