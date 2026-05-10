"""测试 round_index 序列化往返."""

import json
from typing import TYPE_CHECKING

import aiofiles

from experiments.ablation._io import dump_variant_results_jsonl
from experiments.ablation.cli import _load_variant_results
from experiments.ablation.types import Variant, VariantResult

if TYPE_CHECKING:
    from pathlib import Path


async def test_round_index_roundtrip(tmp_path: Path):
    """Given VariantResult with round_index=5, When dump then load, Then round_index preserved."""
    vr = VariantResult(
        scenario_id="s1",
        variant=Variant.FULL,
        decision={},
        result_text="",
        event_id=None,
        stages={},
        latency_ms=0.0,
        round_index=5,
    )
    path = tmp_path / "results.jsonl"
    await dump_variant_results_jsonl(path, [vr])

    lines = path.read_text().strip().split("\n")
    loaded = json.loads(lines[0])
    assert loaded["round_index"] == 5


async def test_round_index_default_zero(tmp_path: Path):
    """Given VariantResult with default round_index, When dump then load, Then round_index=0."""
    vr = VariantResult(
        scenario_id="s1",
        variant=Variant.FULL,
        decision={},
        result_text="",
        event_id=None,
        stages={},
        latency_ms=0.0,
    )
    path = tmp_path / "results.jsonl"
    await dump_variant_results_jsonl(path, [vr])

    lines = path.read_text().strip().split("\n")
    loaded = json.loads(lines[0])
    assert loaded["round_index"] == 0


async def test_load_variant_results_restores_round_index(tmp_path: Path):
    """Given JSONL with round_index=5, When _load_variant_results, Then VariantResult.round_index==5."""
    path = tmp_path / "results.jsonl"
    async with aiofiles.open(path, "w") as f:
        await f.write(json.dumps({
            "scenario_id": "s1",
            "variant": "full",
            "decision": {},
            "stages": {},
            "latency_ms": 0.0,
            "round_index": 5,
        }) + "\n")

    results = await _load_variant_results(path)
    assert len(results) == 1
    assert results[0].round_index == 5
    assert results[0].scenario_id == "s1"
