from types import SimpleNamespace

import pytest
from consts.exceptions import TagManagementConflictError, ValidationError
from database.tag_management_db import TagManagementDB


def test_replacement_validation_rejects_more_than_100_values_before_mutation():
    with pytest.raises(TagManagementConflictError) as error:
        TagManagementDB._validate_replacement_values(list(range(1, 102)), [])

    assert error.value.details == {
        "limit": 100,
        "current_count": 101,
        "scope": "assignment",
    }


def test_replacement_validation_rejects_multiple_single_select_values():
    definition = SimpleNamespace(definition_id=7, selection_mode="single_select")

    with pytest.raises(ValidationError, match="single-select"):
        TagManagementDB._validate_replacement_values(
            [11, 12],
            [(SimpleNamespace(value_id=11), definition), (SimpleNamespace(value_id=12), definition)],
        )


def test_replacement_validation_requires_every_active_bound_value():
    with pytest.raises(ValidationError, match="active and belong"):
        TagManagementDB._validate_replacement_values(
            [11, 12], [(SimpleNamespace(value_id=11), SimpleNamespace(definition_id=7, selection_mode="multi_select"))]
        )
