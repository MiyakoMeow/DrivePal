"""reporter markdown 生成测试."""

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.reporter import (
    _format_calls,
    _format_reasoning_type,
    _md_memory_type_detail,
    _md_overview,
    _md_query_analysis,
    _md_reasoning_cross_comparison,
    _md_summary,
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


class TestMdOverview:
    """_md_overview 测试."""

    def test_contains_header_and_table(self) -> None:
        """测试总览包含标题和各类记忆类型行."""
        md = _md_overview(_make_report_data())
        assert "## 1. 总览" in md
        assert "| gold" in md
        assert "| none" in md
        assert "42.00%" in md
        assert "10.00%" in md

    def test_shows_delta_for_non_gold(self) -> None:
        """测试非 gold 类型显示相对 gold 的百分比差值."""
        md = _md_overview(_make_report_data())
        assert "Δ%" in md
        assert "-76.19%" in md

    def test_gold_no_delta_column(self) -> None:
        """测试 gold 行的 Delta 列显示为横杠."""
        md = _md_overview(_make_report_data())
        lines = md.split("\n")
        gold_lines = [
            line for line in lines if line.startswith("| gold |") and "| - |" in line
        ]
        assert len(gold_lines) == 1
        gold_parts = gold_lines[0].split("|")
        delta_col_index = 6
        assert gold_parts[delta_col_index].strip() == "-"

    def test_shows_total_failed(self) -> None:
        """测试显示失败数量."""
        md = _md_overview(_make_report_data())
        lines = md.split("\n")
        gold_line = next(line for line in lines if line.startswith("| gold |"))
        none_line = next(line for line in lines if line.startswith("| none |"))
        gold_parts = gold_line.split("|")
        none_parts = none_line.split("|")
        failed_col_index = 9
        assert gold_parts[failed_col_index].strip() == "0"
        assert none_parts[failed_col_index].strip() == "2"

    def test_shows_memory_score_for_non_gold(self) -> None:
        """测试显示memory score."""
        md = _md_overview(_make_report_data())
        assert "23.80%" in md

    def test_empty_report_data(self) -> None:
        """测试空数据时显示无数据提示."""
        md = _md_overview({})
        assert "## 1. 总览" in md
        assert "无数据" in md

    def test_no_gold_all_delta_dash(self) -> None:
        """测试无 GOLD 类型时所有行 Delta 列为横杠."""
        none_data: dict[BenchMemoryMode, dict[str, Any]] = {
            BenchMemoryMode.NONE: {
                "exact_match_rate": 0.5,
                "state_f1_positive": 0.6,
                "state_f1_change": 0.5,
                "avg_pred_calls": 3.0,
                "avg_output_token": 100.0,
                "total_failed": 0,
            },
        }
        md = _md_overview(none_data)
        lines = md.split("\n")
        data_lines = [line for line in lines if line.startswith("| none |")]
        assert len(data_lines) == 1
        parts = data_lines[0].split("|")
        header_line = next(line for line in lines if line.startswith("| 记忆类型"))
        headers = [h.strip() for h in header_line.split("|") if h.strip()]
        delta_idx = headers.index("Δ% (vs Gold)")
        assert parts[delta_idx + 1].strip() == "-"


class TestMdMemoryTypeDetail:
    """_md_memory_type_detail 测试."""

    def test_gold_section(self) -> None:
        """测试 gold 类型详细段落包含关键指标."""
        data = _make_report_data()
        md = _md_memory_type_detail(
            BenchMemoryMode.GOLD, data[BenchMemoryMode.GOLD], None
        )
        assert "### gold" in md
        assert "42.00%" in md
        assert "偏好冲突" in md
        assert "条件约束" in md

    def test_non_gold_shows_gold_comparison(self) -> None:
        """测试非 gold 类型段落显示与 gold 的对比."""
        data = _make_report_data()
        gold_metric = data[BenchMemoryMode.GOLD]
        md = _md_memory_type_detail(
            BenchMemoryMode.NONE, data[BenchMemoryMode.NONE], gold_metric
        )
        assert "与 Gold 对比" in md

    def test_gold_no_comparison(self) -> None:
        """测试 gold 类型段落不包含与自身的对比."""
        data = _make_report_data()
        md = _md_memory_type_detail(
            BenchMemoryMode.GOLD, data[BenchMemoryMode.GOLD], None
        )
        assert "与 Gold 对比" not in md

    def test_shows_reasoning_type_table(self) -> None:
        """测试按推理类型细分表格包含预期标签和数据."""
        data = _make_report_data()
        md = _md_memory_type_detail(
            BenchMemoryMode.GOLD, data[BenchMemoryMode.GOLD], None
        )
        assert "| 偏好冲突 |" in md
        assert "| 条件约束 |" in md
        assert "35.70%" in md

    def test_shows_academic_explanation(self) -> None:
        """测试详细分析包含指标学术说明."""
        data = _make_report_data()
        md = _md_memory_type_detail(
            BenchMemoryMode.GOLD, data[BenchMemoryMode.GOLD], None
        )
        assert "Exact Match Rate" in md
        assert "F1 Positive" in md

    def test_no_reasoning_type_no_table(self) -> None:
        """测试无推理类型时不输出细分表格."""
        metric: dict[str, Any] = {
            "exact_match_rate": 0.5,
            "state_f1_positive": 0.6,
            "state_f1_change": 0.5,
            "state_f1_negative": 0.99,
            "change_accuracy": 0.5,
            "avg_pred_calls": 3.0,
            "avg_output_token": 100.0,
            "total_failed": 0,
        }
        md = _md_memory_type_detail(BenchMemoryMode.GOLD, metric, None)
        assert "按推理类型细分" not in md

    def test_gold_esm_zero_no_comparison(self) -> None:
        """测试 gold ESM 为 0 时不输出与 Gold 对比段落."""
        gold_metric_zero: dict[str, Any] = {
            "exact_match_rate": 0.0,
            "state_f1_positive": 0.0,
            "state_f1_change": 0.0,
            "state_f1_negative": 0.0,
            "change_accuracy": 0.0,
            "avg_pred_calls": 0.0,
            "avg_output_token": 0.0,
            "total_failed": 0,
        }
        none_metric: dict[str, Any] = {
            "exact_match_rate": 0.5,
            "state_f1_positive": 0.6,
            "state_f1_change": 0.5,
            "state_f1_negative": 0.99,
            "change_accuracy": 0.5,
            "avg_pred_calls": 3.0,
            "avg_output_token": 100.0,
            "total_failed": 0,
        }
        md = _md_memory_type_detail(BenchMemoryMode.NONE, none_metric, gold_metric_zero)
        assert "与 Gold 对比" not in md


class TestMdReasoningCrossComparison:
    """_md_reasoning_cross_comparison 测试."""

    def test_contains_section_header(self) -> None:
        """测试交叉对比包含正确的节标题."""
        md = _md_reasoning_cross_comparison(_make_report_data())
        assert "## 3. 按推理类型交叉对比" in md

    def test_contains_table_with_types(self) -> None:
        """测试交叉对比表格包含各推理类型和记忆类型."""
        md = _md_reasoning_cross_comparison(_make_report_data())
        assert "| 偏好冲突 |" in md
        assert "gold" in md
        assert "none" in md

    def test_bolds_max_esm(self) -> None:
        """测试最高 ESM 值以加粗显示."""
        md = _md_reasoning_cross_comparison(_make_report_data())
        lines = md.split("\n")
        pref_lines = [
            line for line in lines if "偏好冲突" in line and line.startswith("|")
        ]
        cond_lines = [
            line for line in lines if "条件约束" in line and line.startswith("|")
        ]
        assert len(pref_lines) == 1
        assert len(cond_lines) == 1
        assert "**35.70%**" in pref_lines[0]
        assert "**45.00%**" in cond_lines[0]
        assert "**7.10%**" not in pref_lines[0]
        assert "**15.00%**" not in cond_lines[0]

    def test_empty_data(self) -> None:
        """测试空数据时显示无数据提示."""
        md = _md_reasoning_cross_comparison({})
        assert "无数据" in md


class TestMdQueryAnalysis:
    """_md_query_analysis 测试."""

    def test_contains_section_header(self) -> None:
        """测试查询分析包含正确的节标题."""
        md = _md_query_analysis(_make_all_results())
        assert "## 4. 单条查询分析" in md

    def test_shows_success_case(self) -> None:
        """测试成功匹配案例在输出中展示."""
        md = _md_query_analysis(_make_all_results())
        assert "完全匹配" in md
        assert "Gary got into the driver" in md

    def test_shows_overmodification_case(self) -> None:
        """测试过度修改案例在输出中展示."""
        md = _md_query_analysis(_make_all_results())
        assert "过度修改" in md
        assert "Patricia was driving" in md

    def test_shows_omission_case(self) -> None:
        """测试遗漏调用案例在输出中展示."""
        md = _md_query_analysis(_make_all_results())
        assert "遗漏" in md

    def test_empty_results(self) -> None:
        """测试空查询数据时显示无数据提示."""
        md = _md_query_analysis({})
        assert "无查询数据" in md

    def test_skips_empty_query_list(self) -> None:
        """测试空查询列表的记忆类型不出现在输出中."""
        results = {BenchMemoryMode.GOLD: []}
        md = _md_query_analysis(results)
        assert "### gold" not in md

    def test_fp_sorted_descending(self) -> None:
        """测试过度修改案例按FP降序排列."""
        queries = [
            _make_query("low-fp", fp=1, fn=0),
            _make_query("high-fp", fp=5, fn=0),
            _make_query("mid-fp", fp=3, fn=0),
        ]
        results = {BenchMemoryMode.GOLD: queries}
        md = _md_query_analysis(results)
        lines = md.split("\n")
        fp_values = [
            int(line.split("=")[1])
            for line in lines
            if line.strip().startswith("- FP=")
        ]
        assert fp_values == sorted(fp_values, reverse=True), (
            f"FP 应按降序排列，实际顺序: {fp_values}"
        )

    def test_fn_sorted_descending(self) -> None:
        """测试遗漏调用案例按FN降序排列."""
        queries = [
            _make_query("low-fn", fp=0, fn=1),
            _make_query("high-fn", fp=0, fn=5),
            _make_query("mid-fn", fp=0, fn=3),
        ]
        results = {BenchMemoryMode.GOLD: queries}
        md = _md_query_analysis(results)
        lines = md.split("\n")
        fn_values = [
            int(line.split("=")[1])
            for line in lines
            if line.strip().startswith("- FN=")
        ]
        assert fn_values == sorted(fn_values, reverse=True), (
            f"FN 应按降序排列，实际顺序: {fn_values}"
        )


class TestMdSummary:
    """_md_summary 测试."""

    def test_contains_section_header(self) -> None:
        """测试总结包含正确的节标题."""
        md = _md_summary(_make_report_data())
        assert "## 5. 总结" in md

    def test_contains_ranking(self) -> None:
        """测试总结包含按 ESM 排名的记忆类型."""
        md = _md_summary(_make_report_data())
        assert "1." in md
        assert "gold" in md
        assert "none" in md
        gold_pos = md.find("gold")
        none_pos = md.find("none")
        assert gold_pos < none_pos, "gold should appear before none in ranking"

    def test_gold_highest_rank(self) -> None:
        """测试 gold 类型排名最高."""
        md = _md_summary(_make_report_data())
        assert "42.00%" in md
        assert "10.00%" in md
        gold_42_pos = md.find("gold")
        none_10_pos = md.find("none")
        assert gold_42_pos < none_10_pos, (
            "gold (42%) should rank higher than none (10%)"
        )

    def test_empty_data(self) -> None:
        """测试空数据时总结显示无数据提示."""
        md = _md_summary({})
        assert "无数据" in md

    def test_gold_only_no_theoretical_limit(self) -> None:
        """测试仅 GOLD 类型时不输出理论上限段落."""
        data = _make_report_data()
        gold_only = {BenchMemoryMode.GOLD: data[BenchMemoryMode.GOLD]}
        md = _md_summary(gold_only)
        assert "理论上限" not in md
        assert "gold" in md

    def test_non_gold_no_memory_score_shows_zero(self) -> None:
        """测试非 GOLD 无 memory_score 时显示 0.00%."""
        data = _make_report_data()
        del data[BenchMemoryMode.NONE]["memory_score"]
        md = _md_summary(data)
        assert "0.00%" in md
        assert "理论上限" in md


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
        assert "## 1. 总览" in content
        assert "## 2. 记忆类型详细分析" in content
        assert "## 3. 按推理类型交叉对比" in content
        assert "## 4. 单条查询分析" in content
        assert "## 5. 总结" in content

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
