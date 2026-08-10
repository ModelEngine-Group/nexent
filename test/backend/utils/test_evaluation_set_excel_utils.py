"""Unit tests for ``backend.utils.evaluation_set_excel_utils``.

Tests cover Excel template generation and case parsing for both .xlsx
and .xls (Legacy ``xlrd`` path) formats, including alias resolution,
required-column validation, row-level error reporting, and empty-file handling.
"""

import importlib
import io
import os
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _ensure_real_openpyxl_loaded_for_module_imports():
    """Reload the production module with a fresh ``openpyxl`` before each test.

    Why we don't use ``monkeypatch.setattr(sys.modules, ...)``: the
    production parser binds ``openpyxl.load_workbook`` at module-import
    time.  A sibling fixture that replaces ``sys.modules["openpyxl"]``
    between two test runs of *this* file would leave the parser's bound
    reference pointing at the mock.

    Reloading the parser inside this fixture (which is autouse=True and
    therefore runs before any service-level fixtures) re-binds
    ``openpyxl.load_workbook`` to the freshly-loaded real module.  No
    module-level mutation persists past the test.
    """
    sys.modules.pop("openpyxl", None)
    sys.modules.pop("openpyxl.styles", None)
    importlib.import_module("openpyxl")
    importlib.import_module("openpyxl.styles")
    parser = sys.modules.get("backend.utils.evaluation_set_excel_utils")
    if parser is not None:
        importlib.reload(parser)
    yield

# Force real ``openpyxl`` to win over any MagicMock a sibling test module may
# have installed into ``sys.modules`` earlier in the session.  We must do this
# *before* the module under test is imported, otherwise the bound names
# inside ``evaluation_set_excel_utils`` will reference the MagicMock and
# fail when called.
try:
    _real_openpyxl = importlib.import_module("openpyxl")
    if not callable(getattr(_real_openpyxl, "Workbook", None)):
        raise ImportError("openpyxl.Workbook is not callable")
except Exception:
    # Fallback: try to import it via the OpenPyXL wheels if available.
    sys.modules.pop("openpyxl", None)
    sys.modules.pop("openpyxl.styles", None)
    _real_openpyxl = importlib.import_module("openpyxl")

sys.modules["openpyxl"] = _real_openpyxl
sys.modules["openpyxl.styles"] = importlib.import_module("openpyxl.styles")

# NOTE: ``xlrd`` is optionally stubbed in conftest.py because the production
# code imports it at module load.  For these tests we need a richer fake that
# actually returns a sheet we can drive — the conftest stub is a bare
# ``MagicMock`` which works for the .xlsx path (which doesn't use ``xlrd``)
# but would not survive a .xls parse.  We override the conftest stub here
# before importing the module under test so both paths get a working fake.
class _StubSheet:
    def __init__(self, rows):
        # rows: list of lists of cell values (header row first)
        self.nrows = len(rows)
        self._rows = rows

    def row_values(self, rowx):
        return self._rows[rowx] if rowx < len(self._rows) else []

    def cell_value(self, rowx, colx):
        row = self._rows[rowx] if rowx < len(self._rows) else []
        return row[colx] if colx < len(row) else None


class _StubBook:
    def __init__(self, rows):
        self._sheet = _StubSheet(rows)

    def sheet_by_index(self, idx):
        return self._sheet


class _StubXlrd:
    @staticmethod
    def open_workbook(file_contents=b""):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(file_contents), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        return _StubBook(rows)


# Replace whatever conftest set with our richer fake.  This must run before
# the module under test is (re-)loaded so that the .xls path uses our fake.
_xlrd_stub = types.ModuleType("xlrd")
_xlrd_stub.open_workbook = _StubXlrd.open_workbook
sys.modules["xlrd"] = _xlrd_stub

# Ensure backend is on the path.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import importlib as _importlib  # noqa: E402

# Always force real ``openpyxl`` into sys.modules before reloading the
# production module — sibling fixtures may have left a MagicMock stub there.
for _name in ("openpyxl", "openpyxl.styles", "openpyxl.workbook"):
    sys.modules.pop(_name, None)
try:
    import openpyxl  # noqa: F401
    sys.modules["openpyxl"] = openpyxl
except Exception:
    pass

_existing_module = sys.modules.get("backend.utils.evaluation_set_excel_utils")
if _existing_module is None:
    _module = _importlib.import_module("backend.utils.evaluation_set_excel_utils")
elif getattr(_existing_module, "xlrd", None) is not _xlrd_stub:
    _module = _importlib.reload(_existing_module)
else:
    _module = _existing_module
REQUIRED_HEADERS = _module.REQUIRED_HEADERS
ALL_HEADERS = _module.ALL_HEADERS
_normalize_header = _module._normalize_header
build_evaluation_set_excel_template_bytes = _module.build_evaluation_set_excel_template_bytes
build_evaluation_set_export_bytes = _module.build_evaluation_set_export_bytes
parse_evaluation_cases_from_excel = _module.parse_evaluation_cases_from_excel

# Expose the module object so callers (tests) can reach other helpers.
_evaluation_set_excel_utils = _module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xlsx_bytes(header_row, data_rows):
    """Build a minimal in-memory .xlsx file from row data.

    header_row: list of column headers (str)
    data_rows : list of lists, each row's cell values

    Always uses the real ``openpyxl.Workbook`` even if a sibling test file has
    stubbed ``sys.modules["openpyxl"]`` for its own purposes.
    """
    sys.modules.pop("openpyxl", None)
    sys.modules.pop("openpyxl.styles", None)
    sys.modules.pop("openpyxl.workbook", None)
    sys.modules.pop("openpyxl.workbook.workbook", None)
    Workbook = importlib.import_module("openpyxl").Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(header_row)
    for row in data_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _normalize_header
# ---------------------------------------------------------------------------

class TestNormalizeHeader:
    def test_none_returns_empty_string(self):
        assert _normalize_header(None) == ""

    def test_strips_and_lowercases(self):
        assert _normalize_header("  ANSWER  ") == "answer"
        assert _normalize_header("问题") == "问题"

    def test_trailing_star_stripped(self):
        assert _normalize_header("query*") == "query*"


# ---------------------------------------------------------------------------
# build_evaluation_set_excel_template_bytes
# ---------------------------------------------------------------------------

class TestBuildTemplateBytes:
    def test_returns_bytes(self):
        result = build_evaluation_set_excel_template_bytes()
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_is_valid_xlsx(self):
        """The generated bytes can be loaded back by openpyxl."""
        from openpyxl import load_workbook

        result = build_evaluation_set_excel_template_bytes()
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        assert ws.title == "evaluation_cases"

    def test_header_row_present(self):
        """Headers are on row 2; row 1 is the instruction row."""
        from openpyxl import load_workbook

        result = build_evaluation_set_excel_template_bytes()
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        # Row 1 — instruction descriptions
        row1 = [cell.value for cell in ws[1]]
        assert any("对话" in str(v) for v in row1)
        # Row 2 — actual column headers
        row2 = [cell.value for cell in ws[2]]
        assert "session_id" in row2
        assert "request_id" in row2
        assert "query" in row2
        assert "custom_variables" in row2
        assert "reference_output" in row2

    def test_example_data_present(self):
        """Row 3+ should contain example data."""
        from openpyxl import load_workbook

        result = build_evaluation_set_excel_template_bytes()
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        # Row 3 should be an example data row (not header, not empty)
        row3 = [cell.value for cell in ws[3]]
        assert row3[2] is not None  # query column should have data

    def test_english_language_template(self):
        from openpyxl import load_workbook

        result = build_evaluation_set_excel_template_bytes(language="en")
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        row1 = [cell.value for cell in ws[1]]
        assert any("Session ID" in str(v) for v in row1)
        row2 = [cell.value for cell in ws[2]]
        assert "session_id" in row2


# ---------------------------------------------------------------------------
# build_evaluation_set_export_bytes
# ---------------------------------------------------------------------------

class TestBuildExportBytes:
    def test_returns_bytes(self):
        result = build_evaluation_set_export_bytes("test_set", [])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_includes_new_columns(self):
        from openpyxl import load_workbook

        cases = [
            {
                "case_id": "c1",
                "inputs": {"query": "q1", "session_id": "s1", "request_id": "1"},
                "label": {"answer": "a1"},
            },
        ]
        result = build_evaluation_set_export_bytes("test_set", cases)
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        # Row 2 (headers): session_id, request_id, query, custom_variables, reference_output
        row2 = [cell.value for cell in ws[2]]
        assert row2[0] == "session_id"
        assert row2[1] == "request_id"
        assert row2[2] == "query"
        # Row 3 (data)
        row3 = [cell.value for cell in ws[3]]
        assert row3[0] == "s1"
        assert row3[1] == "1"
        assert row3[2] == "q1"
        assert row3[4] == "a1"

    def test_turn_order_fallback(self):
        """When inputs use 'turn_order' instead of 'request_id'."""
        from openpyxl import load_workbook

        cases = [
            {
                "inputs": {"query": "q1", "turn_order": "3"},
                "label": {"answer": "a1"},
            },
        ]
        result = build_evaluation_set_export_bytes("test_set", cases)
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        row3 = [cell.value for cell in ws[3]]
        assert row3[1] == "3"

    def test_session_id_from_top_level(self):
        """When session_id is at case top-level, not in inputs."""
        from openpyxl import load_workbook

        cases = [
            {
                "inputs": {"query": "q1"},
                "label": {"answer": "a1"},
                "session_id": "top_level_s",
            },
        ]
        result = build_evaluation_set_export_bytes("test_set", cases)
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        row3 = [cell.value for cell in ws[3]]
        assert row3[0] == "top_level_s"

    def test_custom_variables_json_serialization(self):
        from openpyxl import load_workbook

        cases = [
            {
                "inputs": {"query": "q1", "custom_variables": {"lang": "zh", "topic": "math"}},
                "label": {"answer": "a1"},
            },
        ]
        result = build_evaluation_set_export_bytes("test_set", cases)
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        row3 = [cell.value for cell in ws[3]]
        assert row3[3] is not None
        assert "lang" in row3[3]


# ---------------------------------------------------------------------------
# parse_evaluation_cases_from_excel — shared aliases / edge cases
# ---------------------------------------------------------------------------

class TestParseShared:
    """Tests that apply to both .xlsx and .xls paths."""

    def test_unknown_file_extension_raises(self):
        raw = _make_xlsx_bytes(["query", "answer"], [["q", "a"]])
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_evaluation_cases_from_excel("cases.csv", raw)

    def test_header_normalization_trims_and_lowercases(self):
        raw = _make_xlsx_bytes(["  QUERY  ", " ANSWER "], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "q1"

    def test_optional_case_id_column(self):
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", "question one", "answer one"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["case_id"] == "c1"

    def test_alias_caseid_resolves_to_case_id(self):
        raw = _make_xlsx_bytes(
            ["caseid", "query", "answer"],
            [["c2", "q", "a"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["case_id"] == "c2"

    def test_alias_id_resolves_to_case_id(self):
        raw = _make_xlsx_bytes(["id", "query", "answer"], [["i1", "q", "a"]])
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["case_id"] == "i1"

    def test_alias_chinese_columns(self):
        raw = _make_xlsx_bytes(
            ["序号", "问题", "答案"],
            [["x1", "中文问题", "中文答案"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "中文问题"
        assert cases[0]["label"]["answer"] == "中文答案"
        assert cases[0]["case_id"] == "x1"

    def test_required_column_missing(self):
        raw = _make_xlsx_bytes(["session_id"], [["s1"]])
        with pytest.raises(ValueError, match="Missing required column"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_case_id_optional(self):
        """Missing case_id column should not raise — it's optional."""
        raw = _make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["case_id"] is None

    def test_order_no_is_sequential(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["q1", "a1"], ["q2", "a2"], ["q3", "a3"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert [c["order_no"] for c in cases] == [0, 1, 2]

    def test_strips_whitespace_from_cell_values(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["  trimmed  ", "  spaced  "]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["inputs"]["query"] == "trimmed"
        assert cases[0]["label"]["answer"] == "spaced"

    def test_trailing_star_on_header_is_tolerated(self):
        raw = _make_xlsx_bytes(["query*", "answer*"], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "q1"

    def test_empty_cells_in_optional_column_ignored(self):
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["", "q1", "a1"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["case_id"] is None

    # ── New format tests ────────────────────────────────────────────

    def test_new_format_columns(self):
        """Parse Tencent Cloud format: session_id, request_id, query, custom_variables, reference_output."""
        raw = _make_xlsx_bytes(
            ["session_id", "request_id", "query", "custom_variables", "reference_output"],
            [["s1", "1", "hello", '{"lang":"zh"}', "world"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "hello"
        assert cases[0]["inputs"]["session_id"] == "s1"
        assert cases[0]["inputs"]["request_id"] == "1"
        assert cases[0]["label"]["answer"] == "world"
        assert cases[0]["session_id"] == "s1"
        assert cases[0]["turn_order"] == "1"

    def test_reference_output_maps_to_label_answer(self):
        raw = _make_xlsx_bytes(
            ["query", "reference_output"],
            [["q1", "expected answer"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["label"]["answer"] == "expected answer"

    def test_answer_is_optional(self):
        """reference_output / answer column is optional."""
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["q1", ""]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert "answer" not in cases[0]["label"] or cases[0]["label"]["answer"] is None

    def test_custom_variables_parsed_as_json(self):
        raw = _make_xlsx_bytes(
            ["query", "custom_variables"],
            [["q1", '{"lang": "zh", "topic": "math"}']],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["inputs"]["lang"] == "zh"
        assert cases[0]["inputs"]["topic"] == "math"
        # query should still be present
        assert cases[0]["inputs"]["query"] == "q1"

    def test_custom_variables_invalid_json_stored_as_is(self):
        raw = _make_xlsx_bytes(
            ["query", "custom_variables"],
            [["q1", "not-valid-json"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["inputs"]["custom_variables"] == "not-valid-json"

    def test_turn_order_alias(self):
        raw = _make_xlsx_bytes(
            ["query", "turn_order"],
            [["q1", "5"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["inputs"]["request_id"] == "5"

    def test_multi_turn_sessions(self):
        """Two cases in same session with different turn orders."""
        raw = _make_xlsx_bytes(
            ["session_id", "request_id", "query", "answer"],
            [
                ["s1", "1", "first question", "first answer"],
                ["s1", "2", "follow-up question", "follow-up answer"],
                ["s2", "1", "new session question", "new session answer"],
            ],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 3
        assert cases[0]["inputs"]["session_id"] == "s1"
        assert cases[0]["inputs"]["request_id"] == "1"
        assert cases[1]["inputs"]["session_id"] == "s1"
        assert cases[1]["inputs"]["request_id"] == "2"
        assert cases[2]["inputs"]["session_id"] == "s2"

    def test_template_round_trip(self):
        """Generate a template, fill data, and parse it back."""
        template_bytes = build_evaluation_set_excel_template_bytes(language="zh")
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(template_bytes))
        ws = wb.active
        # Data starts at row 3; clear rows 3+ and add our own
        for row in ws.iter_rows(min_row=3):
            for cell in row:
                cell.value = None
        ws.cell(row=3, column=3, value="test query")
        ws.cell(row=3, column=5, value="test answer")

        buf = io.BytesIO()
        wb.save(buf)
        raw = buf.getvalue()

        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) >= 1
        assert cases[0]["inputs"]["query"] == "test query"
        assert cases[0]["label"]["answer"] == "test answer"


# ---------------------------------------------------------------------------
# parse_evaluation_cases_from_excel — .xlsx path
# ---------------------------------------------------------------------------

class TestParseXlsx:
    def test_empty_file_raises(self):
        from openpyxl import Workbook

        wb = Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        with pytest.raises(ValueError, match="no header row"):
            parse_evaluation_cases_from_excel("test.xlsx", buf.getvalue())

    def test_no_cases_raises(self):
        raw = _make_xlsx_bytes(["query", "answer"], [])
        with pytest.raises(ValueError, match="no cases"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_row_missing_query_raises(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["has query", "has answer"], ["", "has answer"]],
        )
        with pytest.raises(ValueError, match="query is required"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_row_missing_answer_is_ok(self):
        """answer is no longer required; row with only query should parse fine."""
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["has query", ""]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "has query"
        assert cases[0]["label"] == {}

    def test_empty_row_is_skipped(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["q1", "a1"], [None, None], ["q2", "a2"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 2

    def test_row_with_case_id_only_raises_missing_query(self):
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", "", ""]],
        )
        with pytest.raises(ValueError, match="query is required"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_multiple_rows_parsed_correctly(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [
                ["first question", "first answer"],
                ["second question", "second answer"],
            ],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert len(cases) == 2
        assert cases[0]["inputs"]["query"] == "first question"
        assert cases[1]["inputs"]["query"] == "second question"
        assert cases[0]["label"]["answer"] == "first answer"

    def test_case_id_in_last_column(self):
        raw = _make_xlsx_bytes(
            ["query", "answer", "case_id"],
            [["q1", "a1", "c1"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        assert cases[0]["case_id"] == "c1"

    def test_filename_case_insensitive(self):
        raw = _make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.XLSX", raw)
        assert len(cases) == 1


# ---------------------------------------------------------------------------
# parse_evaluation_cases_from_excel — .xls (legacy xlrd) path
# ---------------------------------------------------------------------------

class TestParseXls:
    def test_no_header_row_raises(self):
        with pytest.raises(Exception, match=""):
            parse_evaluation_cases_from_excel("test.xls", b"")

    def test_row_missing_query_raises(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [
                ["has query", "has answer"],
                ["", "has answer"],
            ],
        )
        with pytest.raises(ValueError, match="query is required"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_row_missing_answer_is_ok(self):
        """answer is no longer required."""
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["has query", ""]],
        )
        cases = parse_evaluation_cases_from_excel("test.xls", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "has query"
        assert cases[0]["label"] == {}

    def test_no_cases_raises(self):
        raw = _make_xlsx_bytes(["query", "answer"], [])
        with pytest.raises(ValueError, match="no cases"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_optional_case_id_column(self):
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", "q1", "a1"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xls", raw)
        assert len(cases) == 1
        assert cases[0]["case_id"] == "c1"

    def test_multiple_rows(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["q1", "a1"], ["q2", "a2"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xls", raw)
        assert len(cases) == 2
        assert [c["inputs"]["query"] for c in cases] == ["q1", "q2"]

    def test_row_where_only_case_id_is_populated_is_skipped(self):
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", None, None]],
        )
        with pytest.raises(ValueError, match="query is required"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_filename_case_insensitive(self):
        raw = _make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.XLS", raw)
        assert len(cases) == 1

    def test_new_format_columns_xls(self):
        """xls path should also handle new format columns."""
        raw = _make_xlsx_bytes(
            ["session_id", "request_id", "query", "custom_variables", "reference_output"],
            [["s1", "1", "hello", '{"lang":"zh"}', "world"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xls", raw)
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "hello"
        assert cases[0]["inputs"]["session_id"] == "s1"
        assert cases[0]["label"]["answer"] == "world"
