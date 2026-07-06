"""Unit tests for ``backend.utils.evaluation_set_excel_utils``.

Tests cover Excel template generation and case parsing for both .xlsx
(Legacy ``xlrd`` path) formats, including alias resolution, required-column
validation, row-level error reporting, and empty-file handling.
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

# Reload the production module if it was already loaded by a sibling test
# file so the new xlrd stub is used.  ``conftest.py`` installs a stub at
# session collection time, but more importantly each fixture that touches
# ``sys.modules["openpyxl"]`` (e.g. test_agent_evaluation_service) does not
# touch ``sys.modules["xlrd"]`` itself.  So this reload is purely defensive.
# Reload the production module if it was already loaded by a sibling test
# file so the new xlrd stub is used.  ``conftest.py`` installs a stub at
# session collection time, but more importantly each fixture that touches
# ``sys.modules["openpyxl"]`` (e.g. test_agent_evaluation_service) does not
# touch ``sys.modules["xlrd"]`` itself.  So this reload is purely defensive.
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
OPTIONAL_HEADERS = _module.OPTIONAL_HEADERS
ALL_HEADERS = _module.ALL_HEADERS
_normalize_header = _module._normalize_header
build_evaluation_set_excel_template_bytes = _module.build_evaluation_set_excel_template_bytes
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
    # Force a fresh import of openpyxl every call: a sibling test file may have
    # left a MagicMock in sys.modules that breaks ``wb.save`` (which must write
    # a real zip stream).
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
        from openpyxl import load_workbook

        result = build_evaluation_set_excel_template_bytes()
        wb = load_workbook(io.BytesIO(result))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        assert any("问题" in str(h) for h in headers)
        assert any("答案" in str(h) for h in headers)


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
        raw = _make_xlsx_bytes(["query"], [["only query"]])
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
        with pytest.raises(ValueError, match="问题 is required"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_row_missing_answer_raises(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["has query", "has answer"], ["has query", ""]],
        )
        with pytest.raises(ValueError, match="答案 is required"):
            parse_evaluation_cases_from_excel("test.xlsx", raw)

    def test_empty_row_is_skipped(self):
        # openpyxl iter_rows returns a tuple of Nones for empty rows (not None),
        # so the skip depends on whether at least query+answer are present.
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [["q1", "a1"], [None, None], ["q2", "a2"]],
        )
        cases = parse_evaluation_cases_from_excel("test.xlsx", raw)
        # Empty cells: get_col returns None, which is falsy → row skipped.
        assert len(cases) == 2

    def test_row_with_case_id_only_raises_missing_query(self):
        # When only case_id is provided (query and answer are empty strings),
        # the skip-check passes (any([case_id, "", ""]) is True because "c1" is
        # truthy), then query validation fires: get_col("query") → "" → falsy.
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", "", ""]],
        )
        with pytest.raises(ValueError, match="问题 is required"):
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
        # label structure
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
        # Should not raise "unsupported file type"
        cases = parse_evaluation_cases_from_excel("test.XLSX", raw)
        assert len(cases) == 1


# ---------------------------------------------------------------------------
# parse_evaluation_cases_from_excel — .xls (legacy xlrd) path
# ---------------------------------------------------------------------------

class TestParseXls:
    def test_no_header_row_raises(self):
        # xlrd stub wraps openpyxl; an empty bytes buffer raises BadZipFile.
        # We verify the function handles this gracefully (doesn't crash, propagates).
        with pytest.raises(Exception, match=""):
            parse_evaluation_cases_from_excel("test.xls", b"")

    def test_row_missing_query_raises(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [
                ["has query", "has answer"],
                ["", "has answer"],  # missing query
            ],
        )
        with pytest.raises(ValueError, match="问题 is required"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_row_missing_answer_raises(self):
        raw = _make_xlsx_bytes(
            ["query", "answer"],
            [
                ["has query", "has answer"],
                ["has query", ""],  # missing answer
            ],
        )
        with pytest.raises(ValueError, match="答案 is required"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_no_cases_raises(self):
        # Header only, no data rows → xlrd path raises "no cases".
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
        # xlrd: get_cell(None) → str(None) → "none" (truthy) → skip check passes,
        # then query validation fires.
        raw = _make_xlsx_bytes(
            ["case_id", "query", "answer"],
            [["c1", None, None]],
        )
        with pytest.raises(ValueError, match="问题 is required"):
            parse_evaluation_cases_from_excel("test.xls", raw)

    def test_filename_case_insensitive(self):
        raw = _make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        cases = parse_evaluation_cases_from_excel("test.XLS", raw)
        assert len(cases) == 1
