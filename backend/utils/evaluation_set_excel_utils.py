import io
from typing import Any, Dict, List, Optional

import xlrd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


REQUIRED_HEADERS = ["query"]
ALL_HEADERS = ["session_id", "request_id", "query",
               "reference_output", "case_id"]


def _normalize_header(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


# ── Template i18n ───────────────────────────────────────────────────

_INSTRUCTION_ROW = {
    "zh": [
        "对话ID（同一对话的多轮使用相同ID）",
        "请求顺序（同一对话内从1递增）",
        "用户问题（必填*）",
        "参考输出（可选）",
    ],
    "en": [
        "Session ID (same for all turns in one conversation)",
        "Turn order (increments from 1 within a session)",
        "User query (required*)",
        "Reference output (optional)",
    ],
}

_TEMPLATE_HEADERS = {
    "zh": ["session_id", "request_id", "query", "reference_output"],
    "en": ["session_id", "request_id", "query", "reference_output"],
}

_TEMPLATE_EXAMPLE_ROWS = {
    "zh": [
        ["s1", "1", "1+1等于几？", "2"],
        ["s1", "2", "再乘以3呢？", "6"],
        ["s2", "1", "中国首都是哪里？", "北京"],
    ],
    "en": [
        ["s1", "1", "What is 1+1?", "2"],
        ["s2", "1", "What is the capital of France?", "Paris"],
        ["s2", "2", "What is its population?", "About 2.1 million"],
    ],
}


def build_evaluation_set_excel_template_bytes(language: str = "zh") -> bytes:
    """Build a downloadable XLSX template.

    Layout:
      Row 1 – instruction / description row
      Row 2 – column headers
      Row 3+ – example data (multi-turn sessions)
    """
    headers = _TEMPLATE_HEADERS.get(language, _TEMPLATE_HEADERS["zh"])
    instructions = _INSTRUCTION_ROW.get(language, _INSTRUCTION_ROW["zh"])
    example_rows = _TEMPLATE_EXAMPLE_ROWS.get(language, _TEMPLATE_EXAMPLE_ROWS["zh"])

    wb = Workbook()
    ws = wb.active
    ws.title = "evaluation_cases"

    # Row 1 – instruction / description
    ws.append(instructions)
    ws.freeze_panes = "A3"

    # Row 2 – headers
    ws.append(headers)

    # Styling
    bold = Font(bold=True)
    instruction_font = Font(italic=True, color="808080")
    required_fill = PatternFill(start_color="FFF7E6", end_color="FFF7E6", fill_type="solid")

    # Style the instruction row
    for col_idx in range(1, len(instructions) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = instruction_font

    # Style the header row
    for col_idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col_idx)
        cell.font = bold
        if title == "query":
            cell.fill = required_fill

    # Column widths
    ws.column_dimensions["A"].width = 15  # session_id
    ws.column_dimensions["B"].width = 12  # request_id
    ws.column_dimensions["C"].width = 50  # query
    ws.column_dimensions["D"].width = 50  # reference_output

    # Example rows
    for row in example_rows:
        ws.append(row)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_evaluation_set_export_bytes(set_name: str, cases: List[Dict[str, Any]]) -> bytes:
    """Build an XLSX file containing all cases of an evaluation set.

    Produces the same column layout as the import template so the file can
    be round-tripped via the upload endpoint.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "evaluation_cases"

    instructions = _INSTRUCTION_ROW["zh"]
    headers = _TEMPLATE_HEADERS["zh"]

    # Row 1 – instructions
    ws.append(instructions)
    # Row 2 – headers
    ws.append(headers)
    ws.freeze_panes = "A3"

    # Styling
    bold = Font(bold=True)
    instruction_font = Font(italic=True, color="808080")
    required_fill = PatternFill(start_color="FFF7E6", end_color="FFF7E6", fill_type="solid")

    for col_idx in range(1, len(instructions) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = instruction_font

    for col_idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col_idx)
        cell.font = bold
        if title == "query":
            cell.fill = required_fill

    # Column widths
    ws.column_dimensions["A"].width = 15  # session_id
    ws.column_dimensions["B"].width = 12  # request_id
    ws.column_dimensions["C"].width = 50  # query
    ws.column_dimensions["D"].width = 50  # reference_output

    for case in cases:
        inputs = case.get("inputs") or {}
        label = case.get("label") or {}
        session_id = inputs.get("session_id") or case.get("session_id") or ""
        turn_order = inputs.get("request_id") or inputs.get("turn_order") or case.get("turn_order") or ""
        query = inputs.get("query", "")
        answer = label.get("answer", "")
        ws.append([session_id, turn_order, query, answer])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_evaluation_cases_from_excel(filename: str, raw: bytes) -> List[Dict[str, Any]]:
    """Parse evaluation cases from .xlsx or .xls.

    Expected headers (case-insensitive, trailing * ignored):
      - session_id
      - request_id  (or turn_order)
      - query       (or 问题) – required
      - reference_output  (or answer, 答案)

    Chinese aliases (old format) are also recognized for backward compatibility:
        序号 / case_id / caseid / id  -> case_id
        问题 / query                  -> query
        答案 / answer                 -> answer

    reference_output is mapped to ``label.answer``.

    Returns normalized case dicts compatible with insert_evaluation_set_cases.
    """

    HEADER_ALIASES = {
        # New format (Tencent Cloud compatible)
        "session_id": "session_id",
        "sessionid": "session_id",
        "request_id": "request_id",
        "requestid": "request_id",
        "turn_order": "request_id",
        "turnorder": "request_id",
        "turn": "request_id",
        "query": "query",
        "问题": "query",
        "reference_output": "reference_output",
        "referenceoutput": "reference_output",
        "expected_output": "reference_output",
        "expectedoutput": "reference_output",
        "answer": "reference_output",
        "答案": "reference_output",
        # Old format
        "case_id": "case_id",
        "序号": "case_id",
        "caseid": "case_id",
        "id": "case_id",
        "编号": "case_id",
    }

    def _canonical_header(v: Any) -> Optional[str]:
        key = _normalize_header(v).rstrip("*")
        if not key:
            return None
        return HEADER_ALIASES.get(key)

    lower_name = (filename or "").lower()

    # ── .xlsx branch ────────────────────────────────────────────────
    if lower_name.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            raise ValueError("Excel contains no header row")

        # Scan for the header row: first row with at least one recognized column.
        header_row_idx = 0
        header_row = all_rows[0]
        for r_idx, r in enumerate(all_rows):
            canon_count = sum(1 for v in r if _canonical_header(v) is not None)
            if canon_count >= 1:
                header_row_idx = r_idx
                header_row = r
                break
        else:
            raise ValueError("Excel contains no header row")

        header_map: Dict[str, int] = {}
        for idx, v in enumerate(header_row):
            canon = _canonical_header(v)
            if canon:
                header_map[canon] = idx

        for h in REQUIRED_HEADERS:
            if h not in header_map:
                raise ValueError(f"Missing required column: {h}")

        cases: List[Dict[str, Any]] = []
        for r_idx in range(header_row_idx + 1, len(all_rows)):
            row = all_rows[r_idx]
            excel_row_idx = r_idx + 1  # 1-indexed

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
            answer = get_col("reference_output")
            case_id = get_col("case_id")
            session_id = get_col("session_id")
            request_id = get_col("request_id")

            # Skip fully empty rows
            if not any([query, answer, case_id, session_id, request_id]):
                continue

            if not query:
                raise ValueError(f"Row {excel_row_idx}: query is required")

            # Build inputs dict
            inputs: Dict[str, Any] = {"query": query}
            if session_id:
                inputs["session_id"] = session_id
            if request_id:
                try:
                    inputs["request_id"] = int(request_id)
                except (ValueError, TypeError):
                    inputs["request_id"] = request_id

            normalized: Dict[str, Any] = {
                "case_id": case_id,
                "inputs": inputs,
                "label": {"answer": answer} if answer else {},
                "order_no": len(cases),
            }
            if session_id:
                normalized["session_id"] = session_id
            if request_id:
                try:
                    normalized["turn_order"] = int(request_id)
                except (ValueError, TypeError):
                    normalized["turn_order"] = request_id
            cases.append(normalized)

        if not cases:
            raise ValueError("Excel contains no cases")

        return cases

    # ── .xls branch ─────────────────────────────────────────────────
    if lower_name.endswith(".xls"):
        book = xlrd.open_workbook(file_contents=raw)
        sheet = book.sheet_by_index(0)
        if sheet.nrows < 1:
            raise ValueError("Excel contains no header row")

        # Scan for the header row: first row with at least one recognized column.
        header_row_idx = 0
        header_row = sheet.row_values(0)
        for r_idx in range(sheet.nrows):
            row_vals = sheet.row_values(r_idx)
            canon_count = sum(1 for v in row_vals if _canonical_header(v) is not None)
            if canon_count >= 1:
                header_row_idx = r_idx
                header_row = row_vals
                break
        else:
            raise ValueError("Excel contains no header row")

        header_map: Dict[str, int] = {}
        for idx, v in enumerate(header_row):
            canon = _canonical_header(v)
            if canon:
                header_map[canon] = idx

        for h in REQUIRED_HEADERS:
            if h not in header_map:
                raise ValueError(f"Missing required column: {h}")

        cases: List[Dict[str, Any]] = []
        for r in range(header_row_idx + 1, sheet.nrows):
            excel_row_idx = r + 1  # 1-indexed

            def get_cell(col: str) -> Optional[str]:
                if col not in header_map:
                    return None
                v = sheet.cell_value(r, header_map[col])
                if v is None:
                    return None
                # xlrd may return float for numeric cells
                if isinstance(v, float) and v == int(v):
                    s = str(int(v))
                else:
                    s = str(v).strip()
                return s if s != "" else None

            query = get_cell("query")
            answer = get_cell("reference_output")
            case_id = get_cell("case_id")
            session_id = get_cell("session_id")
            request_id = get_cell("request_id")
            if not any([query, answer, case_id, session_id, request_id]):
                continue

            if not query:
                raise ValueError(f"Row {excel_row_idx}: query is required")

            inputs: Dict[str, Any] = {"query": query}
            if session_id:
                inputs["session_id"] = session_id
            if request_id:
                try:
                    inputs["request_id"] = int(request_id)
                except (ValueError, TypeError):
                    inputs["request_id"] = request_id

            normalized: Dict[str, Any] = {
                "case_id": case_id,
                "inputs": inputs,
                "label": {"answer": answer} if answer else {},
                "order_no": len(cases),
            }
            if session_id:
                normalized["session_id"] = session_id
            if request_id:
                try:
                    normalized["turn_order"] = int(request_id)
                except (ValueError, TypeError):
                    normalized["turn_order"] = request_id
            cases.append(normalized)

        if not cases:
            raise ValueError("Excel contains no cases")

        return cases

    raise ValueError("Unsupported file type. Please upload .xlsx or .xls")
