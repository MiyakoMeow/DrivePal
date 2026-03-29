"""Tests for PrepareRunner."""

import json
from unittest.mock import MagicMock, patch

from app.experiment.runners.prepare import prepare


def _mock_dataset(name):
    if name == "sgd_calendar":
        return [
            {"input": f"sgd input {i}", "type": "event_add", "id": f"sgd_{i}"}
            for i in range(20)
        ]
    if name == "scheduler":
        return [
            {
                "input": f"sched input {i}",
                "type": "schedule_check",
                "id": f"scheduler_{i}",
            }
            for i in range(20)
        ]
    raise ValueError(f"Unknown dataset: {name}")


def _mock_chat_model():
    model = MagicMock()
    model.generate = MagicMock(
        side_effect=lambda prompt, **kw: f"reply to: {prompt[:20]}",
    )
    return model


def _make_mock_memory_module():
    def factory(data_dir, **kwargs):
        m = MagicMock()
        m.set_default_mode = MagicMock()
        m.write_interaction = MagicMock()
        return m

    return factory


@patch(
    "app.experiment.runners.prepare.MemoryModule",
    side_effect=_make_mock_memory_module(),
)
@patch("app.experiment.runners.prepare.get_chat_model")
@patch("app.experiment.loaders.get_test_cases", side_effect=_mock_dataset)
def test_prepare_creates_directory_structure(
    mock_load,
    mock_get_model,
    mock_mem_cls,
    tmp_path,
):
    mock_get_model.return_value = _mock_chat_model()
    result = prepare(base_dir=str(tmp_path), test_count=5, warmup_ratio=0.7, seed=42)
    run_dir = tmp_path / "exp" / result["run_id"]

    assert (run_dir / "prepared.json").exists()
    assert (run_dir / "warmup" / "sgd_calendar.json").exists()
    assert (run_dir / "warmup" / "scheduler.json").exists()
    assert (run_dir / "stores" / "keyword").is_dir()
    assert (run_dir / "stores" / "llm_only").is_dir()
    assert (run_dir / "stores" / "embeddings").is_dir()
    assert (run_dir / "stores" / "memorybank").is_dir()


@patch(
    "app.experiment.runners.prepare.MemoryModule",
    side_effect=_make_mock_memory_module(),
)
@patch("app.experiment.runners.prepare.get_chat_model")
@patch("app.experiment.loaders.get_test_cases", side_effect=_mock_dataset)
def test_prepare_splits_correctly(mock_load, mock_get_model, mock_mem_cls, tmp_path):
    mock_get_model.return_value = _mock_chat_model()
    result = prepare(base_dir=str(tmp_path), test_count=5, warmup_ratio=0.7, seed=42)

    for ds_stats in result["datasets"].values():
        assert ds_stats["test_count"] + ds_stats["warmup_count"] <= 20
        assert ds_stats["test_count"] > 0
        assert ds_stats["warmup_count"] > 0

    test_ids = [tc["id"] for tc in result["test_cases"]]
    assert len(test_ids) == sum(s["test_count"] for s in result["datasets"].values())


@patch(
    "app.experiment.runners.prepare.MemoryModule",
    side_effect=_make_mock_memory_module(),
)
@patch("app.experiment.runners.prepare.get_chat_model")
@patch("app.experiment.loaders.get_test_cases", side_effect=_mock_dataset)
def test_prepare_reproducible(mock_load, mock_get_model, mock_mem_cls, tmp_path):
    mock_get_model.return_value = _mock_chat_model()

    r1 = prepare(base_dir=str(tmp_path / "a"), test_count=5, seed=42)
    r2 = prepare(base_dir=str(tmp_path / "b"), test_count=5, seed=42)

    inputs1 = [tc["input"] for tc in r1["test_cases"]]
    inputs2 = [tc["input"] for tc in r2["test_cases"]]
    assert inputs1 == inputs2


@patch(
    "app.experiment.runners.prepare.MemoryModule",
    side_effect=_make_mock_memory_module(),
)
@patch("app.experiment.runners.prepare.get_chat_model")
@patch("app.experiment.loaders.get_test_cases", side_effect=_mock_dataset)
def test_prepare_warmup_file_format(mock_load, mock_get_model, mock_mem_cls, tmp_path):
    mock_get_model.return_value = _mock_chat_model()
    result = prepare(base_dir=str(tmp_path), test_count=5, warmup_ratio=0.7, seed=42)
    run_dir = tmp_path / "exp" / result["run_id"]

    for ds_name in ["sgd_calendar", "scheduler"]:
        path = run_dir / "warmup" / f"{ds_name}.json"
        items = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(items, list)
        assert len(items) > 0
        for item in items:
            assert "id" in item
            assert "input" in item
            assert "type" in item
            assert "response" in item
            assert item["response"].startswith("reply to:")
