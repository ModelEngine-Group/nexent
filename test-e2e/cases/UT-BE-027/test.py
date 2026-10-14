"""D1 contracts for tags, HITL, model catalog, logging and sandbox cleanup."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


STAGE = pytest.mark.stage("D1")




@STAGE
@pytest.mark.case_id("UT-BE-027")
def test_legacy_hitl_fields_are_rejected_and_normal_query_remains_valid() -> None:
    from consts.model import AgentRequest

    assert AgentRequest(query="continue safely").query == "continue safely"
    for legacy_field, value in (
        ("enable_hitl", True),
        ("hitl_run_id", "00000000-0000-0000-0000-000000000001"),
        ("hitl_after_event", 1),
    ):
        with pytest.raises(PydanticValidationError, match="Legacy human interaction fields"):
            AgentRequest.model_validate({"query": "continue safely", legacy_field: value})






