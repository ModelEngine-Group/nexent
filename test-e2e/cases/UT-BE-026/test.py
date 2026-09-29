"""D1 contracts for tags, HITL, model catalog, logging and sandbox cleanup."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


STAGE = pytest.mark.stage("D1")


@STAGE
@pytest.mark.case_id("UT-BE-026")
def test_tag_governance_translates_capacity_conflict_and_usage(monkeypatch) -> None:
    from consts.exceptions import TagManagementConflictError
    from services.tag_management_service import TagManagementService

    for message, scope in [
        ("Tag definition limit exceeded", "definition"),
        ("Tag value limit exceeded", "value"),
        ("Resource tag assignment limit exceeded", "assignment"),
    ]:
        with pytest.raises(TagManagementConflictError) as caught:
            TagManagementService._translate_database_error(RuntimeError(message))
        assert caught.value.details["scope"] == scope

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.delete_definition",
        lambda *_args, **_kwargs: {"active_value_count": 1, "active_usage_count": 2},
    )
    with pytest.raises(TagManagementConflictError) as caught:
        TagManagementService.delete_definition("tenant-a", 1, 7, "actor-a")
    assert caught.value.details == {
        "definition_id": 7,
        "active_value_count": 1,
        "active_usage_count": 2,
    }








