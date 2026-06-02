import io
from typing import List, Optional, Dict, Any

import xlrd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


REQUIRED_HEADERS = ["query", "answer"]
OPTIONAL_HEADERS = ["context", "case_id"]
ALL_HEADERS = REQUIRED_HEADERS + OPTIONAL_HEADERS


def _normalize_header(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


def build_evaluation_set_excel_template_bytes() -> bytes:
    """Build a downloadable XLSX template.

    Column order puts required fields first.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "evaluation_cases"

    headers = [
        "query*",
        "answer*",
        "context",
        "case_id",
    ]

    ws.append(headers)
    ws.freeze_panes = "A2"

    # Styling
    bold = Font(bold=True)
    required_fill = PatternFill(start_color="FFF7E6", end_color="FFF7E6", fill_type="solid")

    for col_idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = bold
        if title.endswith("*"):
            cell.fill = required_fill

    # Column widths
    ws.column_dimensions["A"].width = 50  # query
    ws.column_dimensions["B"].width = 50  # answer
    ws.column_dimensions["C"].width = 60  # context
    ws.column_dimensions["D"].width = 24  # case_id

    # Example rows
    ws.append([
        "1+1等于几？",
        "2",
        "",
        "c1",
    ])
    ws.append([
        "根据上下文回答：小明今年10岁，明年几岁？",
        "11岁",
        "小明今年10岁。",
        "c2",
    ])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_evaluation_cases_from_excel(filename: str, raw: bytes) -> List[Dict[str, Any]]:
    """Parse evaluation cases from .xlsx or .xls.

    Expected headers: query, answer, context, case_id (case-insensitive).
    A trailing '*' in header is allowed (e.g. query*).

    Returns normalized case dicts compatible with insert_evaluation_set_cases.
    """

    lower_name = (filename or "").lower()
    if lower_name.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header_row = next(rows, None)
        if not header_row:
            raise ValueError("Excel contains no header row")

        header_map: Dict[str, int] = {}
        for idx, v in enumerate(header_row):
            key = _normalize_header(v).rstrip("*")
            if key:
                header_map[key] = idx

        for h in REQUIRED_HEADERS:
            if h not in header_map:
                raise ValueError(f"Missing required column: {h}")

        cases: List[Dict[str, Any]] = []
        for excel_row_idx, row in enumerate(rows, start=2):
            if row is None:
                continue

            def get_col(col: str) -> Optional[str]:
                if col not in header_map:
                    return None
                v = row[header_map[col]] if header_map[col] < len(row) else None
                if v is None:
                    return None
                s = str(v).strip()
                return s if s != "" else None

            query = get_col("query")
            answer = get_col("answer")
            context = get_col("context")
            case_id = get_col("case_id")

            # Skip fully empty rows
            if not any([query, answer, context, case_id]):
                continue

            if not query:
                raise ValueError(f"Row {excel_row_idx}: query is required")
            if not answer:
                raise ValueError(f"Row {excel_row_idx}: answer is required")

            normalized: Dict[str, Any] = {
                "case_id": case_id,
                "inputs": {"query": query, **({"context": context} if context is not None else {})},
                "label": {"answer": answer},
                "order_no": len(cases),
            }
            cases.append(normalized)

        if not cases:
            raise ValueError("Excel contains no cases")

        return cases

    if lower_name.endswith(".xls"):
        book = xlrd.open_workbook(file_contents=raw)
        sheet = book.sheet_by_index(0)
        if sheet.nrows < 1:
            raise ValueError("Excel contains no header row")

        header_row = sheet.row_values(0)
        header_map: Dict[str, int] = {}
        for idx, v in enumerate(header_row):
            key = _normalize_header(v).rstrip("*")
            if key:
                header_map[key] = idx

        for h in REQUIRED_HEADERS:
            if h not in header_map:
                raise ValueError(f"Missing required column: {h}")

        cases: List[Dict[str, Any]] = []
        for r in range(1, sheet.nrows):
            excel_row_idx = r + 1

            def get_cell(col: str) -> Optional[str]:
                if col not in header_map:
                    return None
                v = sheet.cell_value(r, header_map[col])
                if v is None:
                    return None
                s = str(v).strip()
                return s if s != "" else None

            query = get_cell("query")
            answer = get_cell("answer")
            context = get_cell("context")
            case_id = get_cell("case_id")

            if not any([query, answer, context, case_id]):
                continue

            if not query:
                raise ValueError(f"Row {excel_row_idx}: query is required")
            if not answer:
                raise ValueError(f"Row {excel_row_idx}: answer is required")

            normalized: Dict[str, Any] = {
                "case_id": case_id,
                "inputs": {"query": query, **({"context": context} if context is not None else {})},
                "label": {"answer": answer},
                "order_no": len(cases),
            }
            cases.append(normalized)

        if not cases:
            raise ValueError("Excel contains no cases")

        return cases

    raise ValueError("Unsupported file type. Please upload .xlsx or .xls")
