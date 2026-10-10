"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")
















@STAGE
@pytest.mark.case_id("UT-BE-020")
def test_evaluation_excel_parser_handles_aliases_empty_rows_and_required_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils import evaluation_set_excel_utils as excel

    rows = [
        ("说明", None, None),
        (" SESSION_ID* ", "问题", "Expected_Output"),
        (1.0, "What is Nexent?", "An agent platform"),
        (None, None, None),
    ]
    monkeypatch.setattr(excel, "_load_rows", lambda filename, raw: rows)
    cases = excel.parse_evaluation_cases_from_excel("cases.xlsx", b"fixture")
    assert len(cases) == 1
    assert cases[0]["inputs"] == {"query": "What is Nexent?", "session_id": "1"}
    assert cases[0]["label"] == {"answer": "An agent platform"}
    assert cases[0]["session_id"] == "1"
    assert cases[0].get("order_no") == 0
    monkeypatch.setattr(excel, "_load_rows", lambda filename, raw: [("answer",), ("only answer",)])
    with pytest.raises(ValueError, match="Missing required column: query"):
        excel.parse_evaluation_cases_from_excel("bad.xlsx", b"fixture")










