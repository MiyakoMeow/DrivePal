"""E2E smoke test: execute → judge pipeline (all mocked)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.experiment.runners.execute import execute
from app.experiment.runners.judge import judge
from app.memory.types import MemoryMode


def _make_prepared_dir(tmp_path: Path) -> Path:
    base = tmp_path / "exp" / "e2e_test"
    results_dir = base / "results"
    results_dir.mkdir(parents=True)

    for mode in MemoryMode:
        mode_dir = base / "stores" / mode.value
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "events.json").write_text("[]", encoding="utf-8")
        (mode_dir / "strategies.json").write_text("{}", encoding="utf-8")

    test_cases = [
        {"id": "test_0", "input": "提醒我开会", "type": "event_add", "dataset": "test"},
        {
            "id": "test_1",
            "input": "今天有什么安排",
            "type": "schedule_check",
            "dataset": "test",
        },
    ]
    prepared = {
        "run_id": "e2e_test",
        "seed": 42,
        "warmup_ratio": 0.7,
        "datasets": {"test": {"warmup_count": 8, "test_count": 2}},
        "test_cases": test_cases,
    }
    (base / "prepared.json").write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return base


def test_e2e_execute_then_judge(tmp_path: Path) -> None:
    prepared_dir = _make_prepared_dir(tmp_path)

    mock_wf = MagicMock()
    mock_wf.run.return_value = ("提醒已发送: 会议提醒", "evt_001")

    with patch("app.experiment.runners.execute.create_workflow", return_value=mock_wf):
        all_results = execute(str(prepared_dir))

    assert len(all_results["methods"]) == len(MemoryMode)

    results_dir = prepared_dir / "results"
    for mode in MemoryMode:
        raw_file = results_dir / f"{mode.value}_raw.json"
        assert raw_file.exists()
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        assert data["method"] == mode.value
        assert len(data["cases"]) == 2
        assert all(c["task_completed"] for c in data["cases"])

    mock_judge = MagicMock()
    mock_judge.generate.return_value = json.dumps(
        {
            "memory_recall": {"score": 4, "reason": "ok"},
            "relevance": {"score": 4, "reason": "ok"},
            "task_quality": {"score": 4, "reason": "ok"},
            "coherence": {"score": 4, "reason": "ok"},
            "helpfulness": {"score": 4, "reason": "ok"},
        }
    )
    mock_judge.providers = [MagicMock(provider=MagicMock(model="mock-judge"))]

    with patch("app.experiment.runners.judge.get_judge_model", return_value=mock_judge):
        report = judge(str(prepared_dir))

    assert "summary" in report
    for mode in MemoryMode:
        assert mode.value in report["summary"]
        summary = report["summary"][mode.value]
        assert summary["case_count"] == 2
        assert summary["avg_weighted_total"] > 0

    judged_dir = prepared_dir / "judged"
    assert (judged_dir / "final_report.json").exists()
    for mode in MemoryMode:
        assert (judged_dir / f"{mode.value}_judged.json").exists()
