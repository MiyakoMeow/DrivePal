"""Tests for ExecuteRunner."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.experiment.runners.execute import execute


def _setup_prepared(tmp_path: Path) -> Path:
    prepared_dir = tmp_path / "run"
    prepared_dir.mkdir()
    prepared_data = {
        "run_id": "20260101_000000",
        "test_cases": [
            {
                "id": "sgd_0",
                "input": "I need to schedule a meeting",
                "type": "event_add",
            }
        ],
    }
    (prepared_dir / "prepared.json").write_text(
        json.dumps(prepared_data, ensure_ascii=False), encoding="utf-8"
    )
    stores_dir = prepared_dir / "stores"
    for mode in ["keyword", "llm_only", "embeddings", "memorybank"]:
        mode_dir = stores_dir / mode
        mode_dir.mkdir(parents=True)
        (mode_dir / "events.json").write_text("[]", encoding="utf-8")
        (mode_dir / "strategies.json").write_text("{}", encoding="utf-8")
    return prepared_dir


def _mock_workflow():
    wf = MagicMock()
    wf.run.return_value = ("提醒已发送: 开会", "evt_001")
    return wf


@patch("app.experiment.runners.execute.create_workflow")
def test_execute_creates_raw_results(mock_create, tmp_path):
    mock_create.return_value = _mock_workflow()
    prepared_dir = _setup_prepared(tmp_path)

    result = execute(prepared_dir=str(prepared_dir))

    results_dir = prepared_dir / "results"
    assert results_dir.is_dir()
    assert set(result["methods"].keys()) == {
        "keyword",
        "llm_only",
        "embeddings",
        "memorybank",
    }
    for mode in ["keyword", "llm_only", "embeddings", "memorybank"]:
        raw_path = results_dir / f"{mode}_raw.json"
        assert raw_path.exists()
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        assert data["method"] == mode
        assert len(data["cases"]) == 1
        case = data["cases"][0]
        assert case["task_completed"] is True
        assert case["error"] is None
        assert case["id"] == "sgd_0"
        assert case["output"] == "提醒已发送: 开会"
        assert case["event_id"] == "evt_001"


@patch("app.experiment.runners.execute.create_workflow")
def test_execute_handles_failure(mock_create, tmp_path, capsys):
    mock_wf = MagicMock()
    mock_wf.run.side_effect = RuntimeError("LLM failed")
    mock_create.return_value = mock_wf
    prepared_dir = _setup_prepared(tmp_path)

    result = execute(prepared_dir=str(prepared_dir))

    for mode in result["methods"]:
        case = result["methods"][mode]["cases"][0]
        assert case["task_completed"] is False
        assert case["error"] == "LLM failed"

    captured = capsys.readouterr()
    assert "FAIL" in captured.out
    assert "LLM failed" in captured.out
