"""reporter markdown 生成测试."""

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from benchmark.VehicleMemBench import BenchMemoryMode
from benchmark.VehicleMemBench.markdown_formatters import (
    _format_calls,
    _format_reasoning_type,
    _num,
    generate_markdown_report,
)


def _make_report_data() -> dict[BenchMemoryMode, dict[str, Any]]:
    """构造测试用聚合指标."""
    gold: dict[str, Any] = {
        "model": "test-model",
        "memory_type": "gold",
        "completed_tasks": 100,
        "valid_tasks": 100,
        "skipped_tasks": 0,
        "exact_match_rate": 0.42,
        "change_accuracy": 0.617,
        "state_f1_positive": 0.670,
        "state_f1_negative": 0.998,
        "state_acc_positive": 0.69,
        "state_precision_positive": 0.723,
        "state_f1_change": 0.606,
        "state_acc_negative": 0.999,
        "state_precision_change": 0.660,
        "avg_pred_calls": 4.08,
        "avg_output_token": 203.21,
        "skipped_queries": [],
        "total_failed": 0,
        "by_reasoning_type": {
            "preference_conflict": {
                "count": 28,
                "exact_match_rate": 0.357,
                "change_accuracy": 0.589,
                "state_f1_positive": 0.640,
                "state_f1_negative": 0.998,
                "state_acc_positive": 0.679,
                "state_precision_positive": 0.659,
                "state_f1_change": 0.551,
                "state_acc_negative": 0.999,
                "state_precision_change": 0.570,
                "avg_pred_calls": 4.57,
                "avg_output_token": 194.07,
            },
            "conditional_constraint": {
                "count": 20,
                "exact_match_rate": 0.45,
                "change_accuracy": 0.646,
                "state_f1_positive": 0.711,
                "state_f1_negative": 0.998,
                "state_acc_positive": 0.713,
                "state_precision_positive": 0.78,
                "state_f1_change": 0.648,
                "state_acc_negative": 0.999,
                "state_precision_change": 0.72,
                "avg_pred_calls": 4.70,
                "avg_output_token": 252.75,
            },
        },
    }
    none: dict[str, Any] = {
        "model": "test-model",
        "memory_type": "none",
        "completed_tasks": 100,
        "valid_tasks": 100,
        "skipped_tasks": 0,
        "exact_match_rate": 0.10,
        "change_accuracy": 0.362,
        "state_f1_positive": 0.471,
        "state_f1_negative": 0.997,
        "state_acc_positive": 0.483,
        "state_precision_positive": 0.514,
        "state_f1_change": 0.352,
        "state_acc_negative": 0.997,
        "state_precision_change": 0.392,
        "avg_pred_calls": 4.81,
        "avg_output_token": 226.41,
        "skipped_queries": [],
        "total_failed": 2,
        "memory_score": 0.238,
        "by_reasoning_type": {
            "preference_conflict": {
                "count": 28,
                "exact_match_rate": 0.071,
                "change_accuracy": 0.268,
                "state_f1_positive": 0.424,
                "state_f1_negative": 0.997,
                "state_acc_positive": 0.411,
                "state_precision_positive": 0.464,
                "state_f1_change": 0.281,
                "state_acc_negative": 0.998,
                "state_precision_change": 0.321,
                "avg_pred_calls": 4.82,
                "avg_output_token": 212.43,
            },
            "conditional_constraint": {
                "count": 20,
                "exact_match_rate": 0.15,
                "change_accuracy": 0.383,
                "state_f1_positive": 0.47,
                "state_f1_negative": 0.996,
                "state_acc_positive": 0.475,
                "state_precision_positive": 0.527,
                "state_f1_change": 0.395,
                "state_acc_negative": 0.996,
                "state_precision_change": 0.455,
                "avg_pred_calls": 4.65,
                "avg_output_token": 226.0,
            },
        },
    }
    return {
        BenchMemoryMode.GOLD: gold,
        BenchMemoryMode.NONE: none,
    }


def _make_all_results() -> dict[BenchMemoryMode, list[dict[str, Any]]]:
    """构造测试用 per-query 数据."""
    return {
        BenchMemoryMode.GOLD: [
            {
                "query": "At 10:00, Gary got into the driver's seat.",
                "reasoning_type": "preference_conflict",
                "exact_match": True,
                "pred_calls": [
                    {"name": "carcontrol_seat_set_color", "args": {"color": "green"}},
                ],
                "ref_calls": [
                    {"name": "carcontrol_seat_set_color", "args": {"color": "green"}},
                ],
                "state_score": {
                    "FP": 0,
                    "TP": 1,
                    "differences": [],
                },
                "tool_score": {"fn": 0, "tp": 1, "fp": 0},
                "source_file": 1,
                "task_id": 0,
            },
            {
                "query": "At 14:00, Patricia was driving in the industrial zone.",
                "reasoning_type": "conditional_constraint",
                "exact_match": False,
                "pred_calls": [
                    {"name": "carcontrol_ac_set_temperature", "args": {"temp": 22}},
                    {
                        "name": "carcontrol_ac_set_air_circulation",
                        "args": {"mode": "outer"},
                    },
                ],
                "ref_calls": [
                    {
                        "name": "carcontrol_ac_set_air_circulation",
                        "args": {"mode": "inner"},
                    },
                ],
                "state_score": {
                    "FP": 1,
                    "TP": 0,
                    "differences": [
                        "ac.air_circulation: Should be inner but got outer",
                    ],
                },
                "tool_score": {"fn": 1, "tp": 0, "fp": 1},
                "source_file": 1,
                "task_id": 1,
            },
        ],
        BenchMemoryMode.NONE: [
            {
                "query": "At 10:00, Gary got into the driver's seat.",
                "reasoning_type": "preference_conflict",
                "exact_match": False,
                "pred_calls": [],
                "ref_calls": [
                    {"name": "carcontrol_seat_set_color", "args": {"color": "green"}},
                ],
                "state_score": {
                    "FP": 0,
                    "TP": 0,
                    "differences": [
                        "seat.color: Should be green but unchanged",
                    ],
                },
                "tool_score": {"fn": 1, "tp": 0, "fp": 0},
                "source_file": 1,
                "task_id": 0,
            },
        ],
    }


def _make_query(qid: str, *, fp: int = 0, fn: int = 0) -> dict[str, Any]:
    """构造测试用单条查询结果（non-match）."""
    return {
        "query": f"query-{qid}",
        "reasoning_type": "preference_conflict",
        "exact_match": False,
        "pred_calls": [],
        "ref_calls": [],
        "state_score": {"FP": fp, "TP": 0, "differences": []},
        "tool_score": {"fn": fn, "tp": 0, "fp": 0},
        "source_file": 1,
        "task_id": 0,
    }


class TestFormatCalls:
    """_format_calls 测试."""

    def test_empty_calls(self) -> None:
        """测试空调用列表返回无标记."""
        assert _format_calls([]) == "（无）"

    def test_single_call(self) -> None:
        """测试单个调用仅返回函数名."""
        assert _format_calls([{"name": "foo"}]) == "foo"

    def test_multiple_calls(self) -> None:
        """测试多个调用以逗号分隔输出."""
        result = _format_calls([{"name": "foo"}, {"name": "bar"}, {"name": "baz"}])
        assert result == "foo, bar, baz"

    def test_missing_name(self) -> None:
        """测试缺少 name 字段时返回问号."""
        assert _format_calls([{"args": {}}]) == "?"


class TestGenerateMarkdownReport:
    """generate_markdown_report 测试."""

    def test_creates_md_file(self, tmp_path: Path) -> None:
        """测试生成 Markdown 报告文件."""
        generate_markdown_report(tmp_path, _make_report_data(), _make_all_results())
        files = list(tmp_path.glob("report-*.md"))
        assert len(files) == 1

    def test_md_contains_all_sections(self, tmp_path: Path) -> None:
        """测试报告文件包含所有预期章节."""
        generate_markdown_report(tmp_path, _make_report_data(), _make_all_results())
        md_file = next(tmp_path.glob("report-*.md"))
        content = md_file.read_text(encoding="utf-8")
        assert "# VehicleMemBench 基准测试报告" in content
        assert "## 2. 实验组介绍" in content
        assert "## 3. 指标含义" in content
        assert "## 4. 实验结果" in content
        assert "### 4.1 详细指标" in content
        assert "## 5. 结果分析" in content
        assert "### 5.1 各记忆类型表现分析" in content
        assert "### 5.2 按推理类型交叉对比" in content
        assert "### 5.3 问题案例分析" in content

    def test_md_filename_format(self, tmp_path: Path) -> None:
        """测试报告文件名遵循时间戳格式."""
        generate_markdown_report(tmp_path, _make_report_data(), _make_all_results())
        md_file = next(tmp_path.glob("report-*.md"))
        assert re.match(r"report-\d{8}-\d{6}-\d{6}\.md", md_file.name)

    def test_md_contains_metadata(self, tmp_path: Path) -> None:
        """测试报告文件包含生成时间和模型名称."""
        generate_markdown_report(tmp_path, _make_report_data(), _make_all_results())
        md_file = next(tmp_path.glob("report-*.md"))
        content = md_file.read_text(encoding="utf-8")
        assert "生成时间" in content
        assert "test-model" in content

    def test_empty_report_data(self, tmp_path: Path) -> None:
        """测试空数据时不崩溃并生成包含无数据提示的报告."""
        generate_markdown_report(tmp_path, {}, {})
        md_file = next(tmp_path.glob("report-*.md"))
        content = md_file.read_text(encoding="utf-8")
        assert "# VehicleMemBench 基准测试报告" in content
        assert "无数据" in content
        assert "unknown" in content


class TestNum:
    """_num 辅助函数测试."""

    def test_int_passthrough(self) -> None:
        """测试 int 值直接返回."""
        assert _num(42) == 42  # noqa: PLR2004

    def test_float_passthrough(self) -> None:
        """测试 float 值直接返回."""
        assert _num(3.14) == 3.14  # noqa: PLR2004

    def test_none_returns_default(self) -> None:
        """测试 None 返回默认值 0."""
        assert _num(None) == 0

    def test_str_returns_default(self) -> None:
        """测试非数字类型返回默认值."""
        assert _num("bad") == 0

    def test_custom_default(self) -> None:
        """测试自定义默认值."""
        assert _num(None, default=-1) == -1

    def test_zero_passthrough(self) -> None:
        """测试 0 值直接返回（不被替换为 default）."""
        assert _num(0) == 0

    def test_bool_returns_default(self) -> None:
        """测试 bool 类型返回默认值（bool 是 int 子类但不应作为数值）."""
        assert _num(True) == 0  # noqa: FBT003
        assert _num(False) == 0  # noqa: FBT003


class TestFormatReasoningType:
    """_format_reasoning_type 测试."""

    def test_known_type(self) -> None:
        """测试已知类型返回中文标签."""
        assert _format_reasoning_type("preference_conflict") == "偏好冲突"

    def test_unknown_type_fallback(self) -> None:
        """测试未知类型返回原字符串."""
        assert _format_reasoning_type("unknown_type") == "unknown_type"

    def test_none_returns_empty(self) -> None:
        """测试 None 返回空字符串."""
        assert _format_reasoning_type(None) == ""
