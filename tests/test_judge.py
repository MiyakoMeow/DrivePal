"""Tests for JudgeRunner."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.experiment.runners.judge import (
    _compute_weighted_total,
    _parse_judge_response,
    judge,
)


def _setup_prepared_dir(tmp_path: Path, run_id: str = "test_run") -> Path:
    prepared_dir = tmp_path / "exp" / run_id
    results_dir = prepared_dir / "results"
    results_dir.mkdir(parents=True)

    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        raw = {
            "run_id": run_id,
            "method": method,
            "cases": [
                {
                    "id": "test_0",
                    "input": "提醒我开会",
                    "type": "event_add",
                    "output": "提醒已发送: 会议提醒",
                    "raw_output": "会议提醒",
                    "event_id": "evt_001",
                    "latency_ms": 1000.0,
                    "task_completed": True,
                    "semantic_accuracy": 0.8,
                    "context_relatedness": 0.6,
                    "error": None,
                }
            ],
        }
        with open(results_dir / f"{method}_raw.json", "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    return prepared_dir


def _valid_judge_json() -> str:
    return json.dumps(
        {
            "memory_recall": {"score": 4, "reason": "利用了上下文"},
            "relevance": {"score": 5, "reason": "高度相关"},
            "task_quality": {"score": 3, "reason": "基本完成"},
            "coherence": {"score": 4, "reason": "连贯"},
            "helpfulness": {"score": 4, "reason": "有帮助"},
        },
        ensure_ascii=False,
    )


def _make_mock_judge_model(response: str):
    model = MagicMock()
    model.generate.return_value = response
    model.providers = [MagicMock(model="deepseek-chat")]
    return model


@patch("app.experiment.runners.judge.get_judge_model")
def test_judge_creates_judged_files(mock_get, tmp_path):
    mock_get.return_value = _make_mock_judge_model(_valid_judge_json())
    prepared_dir = _setup_prepared_dir(tmp_path)

    report = judge(prepared_dir=str(prepared_dir))

    judged_dir = prepared_dir / "judged"
    assert (judged_dir / "final_report.json").exists()
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        judged_path = judged_dir / f"{method}_judged.json"
        assert judged_path.exists()
        data = json.loads(judged_path.read_text(encoding="utf-8"))
        assert data["method"] == method
        assert len(data["cases"]) == 1
        case = data["cases"][0]
        assert "scores" in case
        assert "weighted_total" in case
        assert case["id"] == "test_0"

    assert "summary" in report
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        assert method in report["summary"]
        s = report["summary"][method]
        assert s["case_count"] == 1
        assert "avg_weighted_total" in s


@patch("app.experiment.runners.judge.get_judge_model")
def test_judge_handles_parse_error(mock_get, tmp_path):
    mock_get.return_value = _make_mock_judge_model("this is not json at all")
    prepared_dir = _setup_prepared_dir(tmp_path)

    judge(prepared_dir=str(prepared_dir))

    judged_dir = prepared_dir / "judged"
    for method in ["keyword", "llm_only", "embeddings", "memorybank"]:
        judged_path = judged_dir / f"{method}_judged.json"
        data = json.loads(judged_path.read_text(encoding="utf-8"))
        case = data["cases"][0]
        assert "judge_error" in case
        assert "scores" not in case


@patch("app.experiment.runners.judge.get_judge_model")
def test_judge_skips_already_judged(mock_get, tmp_path):
    mock_get.return_value = _make_mock_judge_model(_valid_judge_json())
    prepared_dir = _setup_prepared_dir(tmp_path)

    judged_dir = prepared_dir / "judged"
    judged_dir.mkdir(parents=True, exist_ok=True)
    pre_judged = {
        "run_id": "test_run",
        "method": "keyword",
        "judge_model": "deepseek-chat",
        "cases": [
            {
                "id": "test_0",
                "scores": {
                    "memory_recall": {"score": 5, "reason": "pre-judged"},
                    "relevance": {"score": 5, "reason": "pre-judged"},
                    "task_quality": {"score": 5, "reason": "pre-judged"},
                    "coherence": {"score": 5, "reason": "pre-judged"},
                    "helpfulness": {"score": 5, "reason": "pre-judged"},
                },
                "weighted_total": 5.0,
            }
        ],
    }
    (judged_dir / "keyword_judged.json").write_text(
        json.dumps(pre_judged, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    judge(prepared_dir=str(prepared_dir))

    assert mock_get.return_value.generate.call_count == 3
    judged_data = json.loads(
        (judged_dir / "keyword_judged.json").read_text(encoding="utf-8")
    )
    case = judged_data["cases"][0]
    assert case["weighted_total"] == 5.0
    assert case["scores"]["memory_recall"]["reason"] == "pre-judged"


def test_compute_weighted_total():
    scores = {
        "memory_recall": {"score": 4, "reason": "ok"},
        "relevance": {"score": 5, "reason": "ok"},
        "task_quality": {"score": 3, "reason": "ok"},
        "coherence": {"score": 4, "reason": "ok"},
        "helpfulness": {"score": 4, "reason": "ok"},
    }
    result = _compute_weighted_total(scores)
    expected = 4 * 0.25 + 5 * 0.25 + 3 * 0.20 + 4 * 0.15 + 4 * 0.15
    assert result == round(expected, 2)


def test_parse_judge_response_valid():
    raw = _valid_judge_json()
    result = _parse_judge_response(raw)
    assert result is not None
    assert result["memory_recall"]["score"] == 4


def test_parse_judge_response_with_code_block():
    raw = f"```json\n{_valid_judge_json()}\n```"
    result = _parse_judge_response(raw)
    assert result is not None
    assert result["relevance"]["score"] == 5


def test_parse_judge_response_invalid():
    result = _parse_judge_response("not json here")
    assert result is None
