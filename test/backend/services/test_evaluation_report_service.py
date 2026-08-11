"""Unit tests for ``services.evaluation_report_service``.

The module is loaded with ``spec_from_file_location`` while the
``consts`` / ``database`` / ``services`` / ``utils`` packages are stubbed
at ``sys.modules`` level.  ``reportlab`` and ``matplotlib`` are the real
installed libraries, so chart rendering and the final ``doc.build`` run
for real (``setup_reportlab_cjk`` is stubbed to return the built-in
"Helvetica" font so the PDF assembles without a registered CJK font).
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from reportlab.lib.colors import HexColor
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, Spacer, Table

# ---------------------------------------------------------------------------
# 1. Path setup + idempotent package registration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODULE_UNDER_TEST = "services.evaluation_report_service"

_STUB_SLOTS = [
    ("consts.evaluation_report_labels", "get_report_labels"),
    ("database.agent_evaluation_db", "get_agent_evaluation"),
    ("database.evaluation_annotation_db", "list_annotation_schemas"),
    ("database.evaluation_annotation_db", "list_annotations_by_evaluation_id"),
    ("database.evaluator_db", "get_evaluator"),
    ("services.agent_evaluation_service", "_load_all_evaluation_cases"),
    ("services.agent_evaluation_service", "get_evaluation_stats_impl"),
    ("utils.font_utils", "setup_matplotlib_cjk"),
    ("utils.font_utils", "setup_reportlab_cjk"),
]

# 1x1 transparent PNG (valid for reportlab ImageReader)
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _REPO_ROOT / "backend" / name
    pkg.__path__ = [str(backend_path)] if backend_path.is_dir() else []
    sys.modules[name] = pkg
    return pkg


def _mk_mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _install_stubs():
    _consts = _register_package("consts")
    _consts.evaluation_report_labels = _mk_mod(
        "consts.evaluation_report_labels",
        get_report_labels=MagicMock(name="get_report_labels"),
    )
    _db = _register_package("database")
    _db.agent_evaluation_db = _mk_mod(
        "database.agent_evaluation_db",
        get_agent_evaluation=MagicMock(name="get_agent_evaluation"),
    )
    _db.evaluation_annotation_db = _mk_mod(
        "database.evaluation_annotation_db",
        list_annotation_schemas=MagicMock(name="list_annotation_schemas"),
        list_annotations_by_evaluation_id=MagicMock(
            name="list_annotations_by_evaluation_id"
        ),
    )
    _db.evaluator_db = _mk_mod(
        "database.evaluator_db",
        get_evaluator=MagicMock(name="get_evaluator"),
    )
    _svc = _register_package("services")
    _svc.agent_evaluation_service = _mk_mod(
        "services.agent_evaluation_service",
        _load_all_evaluation_cases=MagicMock(name="_load_all_evaluation_cases"),
        get_evaluation_stats_impl=MagicMock(name="get_evaluation_stats_impl"),
    )
    _utils = _register_package("utils")
    _utils.font_utils = _mk_mod(
        "utils.font_utils",
        setup_matplotlib_cjk=MagicMock(name="setup_matplotlib_cjk"),
        setup_reportlab_cjk=MagicMock(name="setup_reportlab_cjk"),
    )


_install_stubs()


def _labels(**over):
    base = {
        "TITLE": "Evaluation Report",
        "SUBTITLE": "{agent} / {id} / {time}",
        "METRIC_SCORE": "Score",
        "METRIC_PASS_RATE": "Pass Rate",
        "METRIC_TOTAL": "Total",
        "SECTION_CONFIG": "Configuration",
        "META_TARGET": "Target",
        "META_SET": "Set",
        "META_NO_SET": " (no set)",
        "META_MODEL": "Model",
        "META_VERSION": "Version",
        "META_CREATED": "Created",
        "META_COMPLETED": "Completed",
        "META_EVALUATORS": "Evaluators",
        "META_PROGRESS": "Progress",
        "SECTION_ANALYSIS": "Analysis",
        "ANALYSIS_TEMPLATE": "n={n} best={best} ({best_score}) worst={worst} ({worst_score})",
        "CHART_SCORES": "Scores",
        "CHART_DISTRIBUTION": "Distribution",
        "SECTION_DETAILS": "Details",
        "COL_HEADER_INDEX": "#",
        "COL_HEADER_QUERY": "Query",
        "COL_HEADER_SCORE": "Score",
        "COL_HEADER_RESULT": "Result",
        "PASS_LABEL": "Pass",
        "FAIL_LABEL": "Fail",
        "STATUS_COMPLETED": "Completed",
        "STATUS_RUNNING": "Running",
        "STATUS_PENDING": "Pending",
        "STATUS_FAILED": "Failed",
        "SUMMARY_TEMPLATE": "agent={agent} total={total} status={status} overall={overall} "
        "level={level} evals={evaluator_count} names={evaluator_names} "
        "pass={pass_count} fail={fail_count} rate={pass_rate}",
        "SUMMARY_EXTRA": " top={top} of {total} quality={quality}",
        "SECTION_OVERVIEW": "Overview",
        "SCORE_EXCELLENT": "Excellent",
        "SCORE_GOOD": "Good",
        "SCORE_NEEDS_IMPROVEMENT": "Needs improvement",
        "SCORE_NA": "N/A",
        "QUALITY_HIGH": "High",
        "QUALITY_MEDIUM": "Medium",
        "QUALITY_LOW": "Low",
        "FOOTER": "Generated {time}",
        "SECTION_ANNOTATIONS": "Annotations",
        "ANNOTATION_COVERAGE": "coverage={coverage}",
        "ANNOTATION_NO_DATA": "No data",
    }
    base.update(over)
    return base


def _default_run(**over):
    run = {
        "agent_name": "AgentX",
        "agent_id": 7,
        "evaluation_set_name": "Set A",
        "judge_model_name": "gpt-4o",
        "agent_version_no": 3,
        "create_time": "2026-08-11T10:00:00Z",
        "update_time": "2026-08-11T11:00:00Z",
        "status": "COMPLETED",
        "progress_done": 3,
        "progress_total": 3,
        "evaluator_config": {"evaluator_ids": [1], "no_set_mode": False},
        "annotation_schema_ids": [10],
        "score_overall": 0.78,
    }
    run.update(over)
    return run


def _default_stats(**over):
    s = {
        "pass_count": 2,
        "fail_count": 1,
        "total": 3,
        "per_evaluator": [{"name": "llm", "avg": 0.85}],
    }
    s.update(over)
    return s


@pytest.fixture
def bundle():
    """Fresh mocks + fresh import of the module for every test."""
    import importlib.util as _ilu

    mocks = {name: MagicMock(name=name) for _, name in _STUB_SLOTS}
    mocks["get_report_labels"].return_value = _labels()
    mocks["setup_matplotlib_cjk"].return_value = "DejaVu Sans"
    mocks["setup_reportlab_cjk"].return_value = "Helvetica"
    for mod_name, attr in _STUB_SLOTS:
        setattr(sys.modules[mod_name], attr, mocks[attr])

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    svc_pkg = _register_package("services")
    if hasattr(svc_pkg, "evaluation_report_service"):
        delattr(svc_pkg, "evaluation_report_service")

    src = _REPO_ROOT / "backend" / "services" / "evaluation_report_service.py"
    spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(src))
    assert spec is not None and spec.loader is not None, f"cannot locate {src}"
    mod = _ilu.module_from_spec(spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    spec.loader.exec_module(mod)
    svc_pkg.evaluation_report_service = mod

    class _Bundle:
        pass

    b = _Bundle()
    b.mod = mod
    b.m = mocks
    return b


def _txt(cell) -> str:
    """Best-effort raw text of a reportlab cell / flowable."""
    if hasattr(cell, "text"):
        return cell.text
    if hasattr(cell, "getValue"):
        return str(cell.getValue())
    return str(cell)


def _plain(cell) -> str:
    if hasattr(cell, "getPlainText"):
        return cell.getPlainText()
    return _txt(cell)


# ---------------------------------------------------------------------------
# 2. Pure helpers
# ---------------------------------------------------------------------------


class TestFmt:
    def test_empty(self, bundle):
        assert bundle.mod._fmt(None) == "-"
        assert bundle.mod._fmt("") == "-"

    def test_valid_iso(self, bundle):
        assert bundle.mod._fmt("2026-08-11T12:34:56Z") == "08/11 12:34"

    def test_invalid_fallback(self, bundle):
        assert bundle.mod._fmt("garbage") == "garbage"


class TestMkStyle:
    def test_defaults_and_override(self, bundle):
        s = bundle.mod._mk_style("X", "Helvetica", fontSize=12)
        assert s.fontName == "Helvetica"
        assert s.fontSize == 12
        assert s.leading == 16
        assert s.textColor == HexColor("#333333")

    def test_custom_text_color(self, bundle):
        s = bundle.mod._mk_style("Y", "CJK", textColor=HexColor("#123456"))
        assert s.fontName == "CJK"
        assert s.textColor == HexColor("#123456")


class TestMetricCard:
    def test_layout(self, bundle):
        styles = bundle.mod._build_report_styles("Helvetica")
        inner = bundle.mod._metric_card(
            "99", "Score", HexColor("#f6ffed"), styles["s_metric_val"], styles["s_metric_lbl"]
        )
        assert isinstance(inner, Table)
        assert _plain(inner._cellvalues[0][0]) == "99"
        assert _plain(inner._cellvalues[1][0]) == "Score"


# ---------------------------------------------------------------------------
# 3. Section builders
# ---------------------------------------------------------------------------


class TestBuildReportHeader:
    def test_appends_title_subtitle_rule_spacer(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_header(story, L, styles, "AgentX", 1, "2026-08-11 12:00")
        assert len(story) == 4
        assert _plain(story[0]) == L["TITLE"]
        assert "AgentX" in _plain(story[1])
        assert "1" in _plain(story[1])
        assert isinstance(story[2], HRFlowable)
        assert isinstance(story[3], Spacer)


class TestBuildReportMetrics:
    def _card_value(self, metric_row, idx):
        card = metric_row._cellvalues[0][idx]
        return _plain(card._cellvalues[0][0])

    def test_overall_number(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_metrics(story, L, styles, 0.8, "67%", 3)
        assert isinstance(story[0], Table)
        assert self._card_value(story[0], 0) == "0.80"
        assert self._card_value(story[0], 1) == "67%"
        assert self._card_value(story[0], 2) == "3"

    def test_overall_none(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_metrics(story, L, styles, None, "-", 0)
        assert self._card_value(story[0], 0) == "-"
        assert isinstance(story[1], Spacer)


class TestBuildReportConfig:
    def _row(self, meta_table, row):
        return [_txt(c) for c in meta_table._cellvalues[row]]

    def test_default_run(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_config(
            story, L, styles, _default_run(), {"llm": 0.85}, False, "Helvetica"
        )
        assert _plain(story[0]) == L["SECTION_CONFIG"]
        meta = story[1]
        assert self._row(meta, 0) == ["Target", "AgentX", "Set", "Set A"]
        assert self._row(meta, 1) == ["Model", "gpt-4o", "Version", "v3"]
        assert "08/11 10:00" in self._row(meta, 2)[1]
        assert "08/11 11:00" in self._row(meta, 2)[3]
        assert self._row(meta, 3) == ["Evaluators", "1", "Progress", "3 / 3"]

    def test_no_set_mode_and_running(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        run = _default_run(
            evaluation_set_name=None,
            status="RUNNING",
            evaluator_config={"evaluator_ids": [1], "no_set_mode": True},
        )
        bundle.mod._build_report_config(story, L, styles, run, {}, True, "Helvetica")
        meta = story[1]
        assert self._row(meta, 0)[3] == "- (no set)"
        assert self._row(meta, 2)[3] == "-"
        assert self._row(meta, 3)[1] == "0"


class TestBuildReportChartsSection:
    def test_empty_buffers(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        chart_path, hist_path = bundle.mod._build_report_charts_section(
            story, L, styles, {"llm": 0.85}, io.BytesIO(), io.BytesIO()
        )
        assert chart_path is None and hist_path is None
        assert isinstance(story[0], PageBreak)
        assert _plain(story[1]) == L["SECTION_ANALYSIS"]
        assert len(story) == 4  # PageBreak + h1 + analysis + spacer
        assert _plain(story[2]) == "n=1 best=llm (0.85) worst=llm (0.85)"

    def test_with_charts_and_analysis(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        chart_path, hist_path = bundle.mod._build_report_charts_section(
            story,
            L,
            styles,
            {"a": 0.9, "b": 0.1},
            io.BytesIO(_PNG_BYTES),
            io.BytesIO(_PNG_BYTES),
        )
        try:
            assert chart_path and hist_path
            assert os.path.exists(chart_path)
            assert os.path.exists(hist_path)
            analysis = _plain(story[2])
            assert "best=a (0.9)" in analysis and "worst=b (0.1)" in analysis
            assert isinstance(story[6], Image)
            assert isinstance(story[9], Image)
        finally:
            for p in (chart_path, hist_path):
                if p and os.path.exists(p):
                    os.unlink(p)


class TestFormatMultiEvaluatorScores:
    def test_colors_and_skip_non_numeric(self, bundle):
        out = bundle.mod._format_multi_evaluator_scores(
            {"a": 0.9, "b": 0.3, "c": "na"}, {"a": 0.5, "b": 0.5}
        )
        assert "#52c41a" in out and "a: <b>0.90</b>" in out
        assert "#ff4d4f" in out and "b: <b>0.30</b>" in out
        assert "c: <b>" not in out
        assert out.count("<br/>") == 1

    def test_threshold_from_map(self, bundle):
        out = bundle.mod._format_multi_evaluator_scores({"a": 0.9}, {"a": 0.95})
        assert "#ff4d4f" in out

    def test_empty(self, bundle):
        assert bundle.mod._format_multi_evaluator_scores({}, {}) == ""


class TestFormatSingleScore:
    def test_pass(self, bundle):
        assert "#52c41a" in bundle.mod._format_single_score(0.9, "pass")

    def test_fail(self, bundle):
        assert "#ff4d4f" in bundle.mod._format_single_score(0.9, "fail")

    def test_unknown_status_falls_back(self, bundle):
        assert "#52c41a" in bundle.mod._format_single_score(0.8, "odd")
        assert "#ff4d4f" in bundle.mod._format_single_score(0.2, "odd")


class TestFormatCaseScoreText:
    def test_dict(self, bundle):
        out = bundle.mod._format_case_score_text({"a": 0.9, "b": 0.1}, "pass", {"a": 0.5})
        assert "<br/>" in out

    def test_scalar(self, bundle):
        assert "<b>0.60</b>" in bundle.mod._format_case_score_text(0.6, "pass", {})

    def test_none_and_str(self, bundle):
        assert bundle.mod._format_case_score_text(None, "", {}) == "-"
        assert bundle.mod._format_case_score_text("raw", "", {}) == "raw"


class TestFormatStatusTag:
    def test_pass_fail(self, bundle):
        L = _labels()
        assert L["PASS_LABEL"] in bundle.mod._format_status_tag("pass", L)
        assert L["FAIL_LABEL"] in bundle.mod._format_status_tag("fail", L)
        assert "#52c41a" in bundle.mod._format_status_tag("pass", L)
        assert "#ff4d4f" in bundle.mod._format_status_tag("fail", L)

    def test_unknown(self, bundle):
        assert bundle.mod._format_status_tag("odd", _labels()) == "odd"


class TestApplyZebraStriping:
    def test_even_rows_only(self, bundle):
        table = MagicMock()
        bundle.mod._apply_zebra_striping(table, 6, HexColor("#f5f5f5"))
        assert table.setStyle.call_count == 2

    def test_no_rows(self, bundle):
        table = MagicMock()
        bundle.mod._apply_zebra_striping(table, 2, HexColor("#f5f5f5"))
        assert table.setStyle.call_count == 0


class TestBuildReportCaseTable:
    def _cases(self):
        return [
            {"inputs": {"query": "hello"}, "score": {"llm": 0.9}, "pass_status": "pass"},
            {"inputs": {"query": "x" * 200}, "score": 0.3, "pass_status": "fail"},
            {"inputs": {}, "score": None, "pass_status": ""},
        ]

    def test_builds_rows(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_case_table(story, L, styles, self._cases(), "Helvetica")
        assert isinstance(story[0], PageBreak)
        assert _plain(story[1]) == L["SECTION_DETAILS"]
        table = story[3]
        assert isinstance(table, Table)
        assert len(table._cellvalues) == 4  # header + 3 cases
        assert "#52c41a" in _txt(table._cellvalues[1][2])  # pass color
        assert len(_txt(table._cellvalues[2][1])) == 150  # query truncated
        assert _txt(table._cellvalues[2][2]) == "<font color='#ff4d4f'><b>0.30</b></font>"
        assert _txt(table._cellvalues[3][2]) == "-"
        assert _txt(table._cellvalues[3][3]) == ""

    def test_threshold_colours(self, bundle):
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_case_table(
            story, L, styles, self._cases(), "Helvetica", evaluator_thresholds={"llm": 0.95}
        )
        assert "#ff4d4f" in _txt(story[3]._cellvalues[1][2])  # 0.9 < 0.95 → fail


class TestCountAnnotationValues:
    def test_counts_and_skips_empty(self, bundle):
        data = {
            1: [{"schema_id": 10, "value": "g"}, {"schema_id": 10, "value": ""}],
            2: [{"schema_id": 11, "value": "h"}, {"schema_id": 10, "value": "g"}],
        }
        assert bundle.mod._count_annotation_values(data, 10) == {"g": 2}


class TestBuildAnnotationRows:
    def test_sorted_desc_with_bar(self, bundle):
        styles = bundle.mod._build_report_styles("Helvetica")
        rows = bundle.mod._build_annotation_rows({"b": 3, "a": 2}, 5, styles["s_body"])
        assert [row[0].text for row in rows] == ["b", "a"]
        assert rows[0][1].text == "<font color='#1677ff'>" + "█" * 20 + "</font>"
        assert rows[1][1].text == "<font color='#1677ff'>" + "█" * 13 + "</font>"
        assert rows[0][2].text == "3 (60%)"
        assert rows[1][2].text == "2 (40%)"

    def test_empty(self, bundle):
        styles = bundle.mod._build_report_styles("Helvetica")
        assert bundle.mod._build_annotation_rows({}, 0, styles["s_body"]) == []


class TestBuildReportAnnotations:
    def _setup(self, bundle, run=None, ann_data=None, schemas=None, total=3):
        bundle.m["list_annotations_by_evaluation_id"].return_value = ann_data or {}
        bundle.m["list_annotation_schemas"].return_value = schemas or []
        L = _labels()
        styles = bundle.mod._build_report_styles("Helvetica")
        story = []
        bundle.mod._build_report_annotations(
            story, L, styles, "Helvetica", "t1", 1, total, run or _default_run()
        )
        return story, L

    def test_no_active_schemas_skips(self, bundle):
        story, _ = self._setup(bundle, run=_default_run(annotation_schema_ids=[]))
        assert story == []
        bundle.m["list_annotations_by_evaluation_id"].assert_called_once_with(
            tenant_id="t1", agent_evaluation_id=1
        )

    def test_active_schema_with_data(self, bundle):
        run = _default_run()
        story, L = self._setup(
            bundle,
            run=run,
            ann_data={1: [{"schema_id": 10, "value": "good"}]},
            schemas=[{"schema_id": 10, "name": "Quality"}],
        )
        assert isinstance(story[0], PageBreak)
        assert _plain(story[1]) == L["SECTION_ANNOTATIONS"]
        assert "Quality" in _plain(story[3])
        assert "coverage=1/3" in _plain(story[3])
        assert isinstance(story[5], Table)

    def test_active_schema_without_data(self, bundle):
        run = _default_run()
        story, L = self._setup(
            bundle, run=run, ann_data={}, schemas=[{"schema_id": 10, "name": "Quality"}]
        )
        assert _plain(story[5]) == L["ANNOTATION_NO_DATA"]

    def test_total_zero_coverage(self, bundle):
        run = _default_run()
        story, _ = self._setup(
            bundle,
            run=run,
            ann_data={1: [{"schema_id": 10, "value": "good"}]},
            schemas=[{"schema_id": 10, "name": "Quality"}],
            total=0,
        )
        assert "coverage=0" in _plain(story[3])

    def test_db_error_swallowed(self, bundle):
        bundle.m["list_annotations_by_evaluation_id"].side_effect = RuntimeError("boom")
        story, _ = self._setup(bundle, run=_default_run(annotation_schema_ids=[10]))
        assert story == []


# ---------------------------------------------------------------------------
# 4. Report data helpers
# ---------------------------------------------------------------------------


class TestLoadEvaluatorThresholdsForReport:
    def _ev(self, **over):
        ev = {"name": "llm", "pass_threshold": 0.6, "score_range_min": 0, "score_range_max": 100}
        ev.update(over)
        return ev

    def test_happy_path(self, bundle):
        bundle.m["get_evaluator"].side_effect = [self._ev(), self._ev(name="judge")]
        run = _default_run(evaluator_config={"evaluator_ids": [1, 2]})
        th, rng, err = bundle.mod._load_evaluator_thresholds_for_report(run, "t1")
        assert th == {"llm": 0.6, "judge": 0.6}
        assert rng == {"llm": (0.0, 100.0), "judge": (0.0, 100.0)}
        assert err == 0
        bundle.m["get_evaluator"].assert_called_with(2, "t1")

    def test_defaults_when_missing(self, bundle):
        bundle.m["get_evaluator"].return_value = {"name": "x"}
        run = _default_run(evaluator_config={"evaluator_ids": [1]})
        th, rng, err = bundle.mod._load_evaluator_thresholds_for_report(run, "t1")
        assert th == {"x": 0.5}
        assert rng == {"x": (0.0, 1.0)}
        assert err == 0

    def test_skip_missing_or_nameless(self, bundle):
        bundle.m["get_evaluator"].side_effect = [None, {"no_name": True}]
        run = _default_run(evaluator_config={"evaluator_ids": [1, 2]})
        th, rng, err = bundle.mod._load_evaluator_thresholds_for_report(run, "t1")
        assert th == {} and rng == {} and err == 0

    def test_error_increments_count(self, bundle):
        bundle.m["get_evaluator"].side_effect = [RuntimeError("boom"), self._ev()]
        run = _default_run(evaluator_config={"evaluator_ids": [1, 2]})
        th, rng, err = bundle.mod._load_evaluator_thresholds_for_report(run, "t1")
        assert th == {"llm": 0.6} and err == 1

    def test_no_evaluator_ids(self, bundle):
        run = _default_run(evaluator_config={})
        th, rng, err = bundle.mod._load_evaluator_thresholds_for_report(run, "t1")
        assert th == {} and rng == {} and err == 0
        bundle.m["get_evaluator"].assert_not_called()


class TestNormalizeOneScore:
    def test_maps_range(self, bundle):
        assert bundle.mod._normalize_one_score(50, (0, 100)) == 0.5

    def test_degenerate_range(self, bundle):
        assert bundle.mod._normalize_one_score(7, (5, 5)) == 0.0

    def test_no_range(self, bundle):
        assert bundle.mod._normalize_one_score(0.7, None) == 0.7

    def test_clamps(self, bundle):
        assert bundle.mod._normalize_one_score(20, (0, 10)) == 1.0
        assert bundle.mod._normalize_one_score(-5, (0, 10)) == 0.0


class TestComputeCaseAvgScore:
    def test_average_of_numeric(self, bundle):
        avg = bundle.mod._compute_case_avg_score({"a": 0.8, "b": 0.2, "c": "na"}, {})
        assert avg == 0.5

    def test_with_ranges(self, bundle):
        avg = bundle.mod._compute_case_avg_score({"a": 50, "b": 0.6}, {"a": (0, 100)})
        assert avg == 0.55

    def test_none_when_no_numeric(self, bundle):
        assert bundle.mod._compute_case_avg_score({"a": "x"}, {}) is None
        assert bundle.mod._compute_case_avg_score({}, {}) is None


class TestComputeNormalizedAvgScores:
    def test_filters(self, bundle):
        cases = [
            {"score": {"a": 0.5}},
            {"score": 0.7},  # non-dict → skipped
            {"score": {"a": "x"}},  # no numeric → None → skipped
            {},
        ]
        out = bundle.mod._compute_normalized_avg_scores(cases, {})
        assert out == [0.5]


class TestBuildReportStyles:
    def test_keys_and_values(self, bundle):
        styles = bundle.mod._build_report_styles("Helvetica")
        for key in (
            "blue", "gray", "light_gray", "dark",
            "s_report_title", "s_subtitle", "s_h1", "s_h2",
            "s_body", "s_small", "s_bold", "s_metric_val",
            "s_metric_lbl", "s_footer",
        ):
            assert key in styles
        assert styles["s_report_title"].fontSize == 20
        assert styles["s_body"].fontName == "Helvetica"
        assert styles["s_small"].fontSize == 9


class TestDrawScoreChart:
    def test_empty_scores(self, bundle):
        buf = io.BytesIO()
        bundle.mod._draw_score_chart({}, buf, "DejaVu Sans")
        assert buf.getvalue()


class TestDrawHistogram:
    def test_empty_scores(self, bundle):
        buf = io.BytesIO()
        bundle.mod._draw_histogram([], buf, "DejaVu Sans")
        assert buf.getvalue()


class TestGenerateReportCharts:
    def test_success(self, bundle):
        chart, hist, ok = bundle.mod._generate_report_charts(
            {"llm": 0.85}, [0.3, 0.6, 0.9]
        )
        assert ok is True
        assert chart.getvalue() and hist.getvalue()

    def test_failure_swallowed(self, bundle):
        bundle.m["setup_matplotlib_cjk"].side_effect = RuntimeError("no font")
        chart, hist, ok = bundle.mod._generate_report_charts({"llm": 0.85}, [0.5])
        assert ok is False
        assert not chart.getvalue() and not hist.getvalue()

    def test_empty_inputs(self, bundle):
        chart, hist, ok = bundle.mod._generate_report_charts({}, [])
        assert ok is True
        assert not chart.getvalue() and not hist.getvalue()


class TestComputeScoreLevel:
    def test_branches(self, bundle):
        L = _labels()
        assert bundle.mod._compute_score_level(0.9, L) == L["SCORE_EXCELLENT"]
        assert bundle.mod._compute_score_level(0.6, L) == L["SCORE_GOOD"]
        assert bundle.mod._compute_score_level(0.4, L) == L["SCORE_NEEDS_IMPROVEMENT"]


class TestComputeQualityLevel:
    def test_branches(self, bundle):
        L = _labels()
        assert bundle.mod._compute_quality_level(8, 10, L) == L["QUALITY_HIGH"]
        assert bundle.mod._compute_quality_level(5, 10, L) == L["QUALITY_MEDIUM"]
        assert bundle.mod._compute_quality_level(1, 10, L) == L["QUALITY_LOW"]


class TestCleanupTempChartFiles:
    def test_no_paths(self, bundle):
        assert bundle.mod._cleanup_temp_chart_files(None, None) == 0

    def test_unlinks_existing(self, bundle):
        f1 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f1.close()
        f2.close()
        assert bundle.mod._cleanup_temp_chart_files(f1.name, f2.name) == 0
        assert not os.path.exists(f1.name) and not os.path.exists(f2.name)

    def test_missing_path_fails(self, bundle):
        assert bundle.mod._cleanup_temp_chart_files("/nope/x.png", None) == 1


# ---------------------------------------------------------------------------
# 5. PDF orchestrator
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def _wire_defaults(self, bundle, run=None, stats=None, cases=None):
        bundle.m["get_agent_evaluation"].return_value = run or _default_run()
        bundle.m["get_evaluation_stats_impl"].return_value = stats or _default_stats()
        bundle.m["_load_all_evaluation_cases"].return_value = cases or [
            {"inputs": {"query": "hello"}, "score": {"llm": 50}, "pass_status": "pass"},
            {"inputs": {"query": "bad"}, "score": {"llm": 10}, "pass_status": "fail"},
            {"inputs": {"query": "mid"}, "score": {"llm": 60}, "pass_status": "pass"},
        ]
        bundle.m["get_evaluator"].return_value = {
            "name": "llm", "pass_threshold": 0.6, "score_range_min": 0, "score_range_max": 100,
        }
        bundle.m["list_annotations_by_evaluation_id"].return_value = {
            1: [{"schema_id": 10, "value": "good"}],
        }
        bundle.m["list_annotation_schemas"].return_value = [
            {"schema_id": 10, "name": "Quality"},
        ]

    def test_success_zh(self, bundle):
        self._wire_defaults(bundle)
        pdf_bytes, fail_count = bundle.mod.generate_agent_evaluation_report_impl(1, "t1")
        assert pdf_bytes[:4] == b"%PDF"
        assert fail_count == 1
        bundle.m["get_report_labels"].assert_called_with("zh")
        bundle.m["get_agent_evaluation"].assert_called_once_with(
            agent_evaluation_id=1, tenant_id="t1"
        )
        bundle.m["_load_all_evaluation_cases"].assert_called_with(1, "t1")
        bundle.m["get_evaluation_stats_impl"].assert_called_with(1, "t1")

    def test_language_en(self, bundle):
        self._wire_defaults(bundle)
        pdf_bytes, _ = bundle.mod.generate_agent_evaluation_report_impl(
            1, "t1", language="en"
        )
        assert pdf_bytes[:4] == b"%PDF"
        bundle.m["get_report_labels"].assert_called_with("en")

    def test_total_zero_and_pending(self, bundle):
        self._wire_defaults(
            bundle,
            run=_default_run(
                status="PENDING",
                overall=None,
                score_overall=None,
                evaluator_config={"evaluator_ids": [1], "no_set_mode": True},
                annotation_schema_ids=[],
            ),
            stats=_default_stats(pass_count=0, fail_count=0, total=0, per_evaluator=[]),
            cases=[],
        )
        pdf_bytes, fail_count = bundle.mod.generate_agent_evaluation_report_impl(2, "t1")
        assert pdf_bytes[:4] == b"%PDF"
        assert fail_count == 0
