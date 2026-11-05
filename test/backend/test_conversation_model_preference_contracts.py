# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preference and selection requests have no optimistic revision contract."""

import pytest
from pydantic import ValidationError

from contracts.model import ConversationModelPreferencePatch, ConversationModelSelectionPatch


@pytest.mark.parametrize("schema,payload", [
    (ConversationModelPreferencePatch, {"parameter_values": {"temperature": 0, "enable_thinking": False}}),
    (ConversationModelSelectionPatch, {"selected_model_id": 17}),
])
def test_preferences_can_be_saved_without_a_version(schema, payload):
    result = schema.model_validate(payload)
    assert "expected_version" not in schema.model_fields
    assert "expected_version" not in result.model_dump()
    assert all(result.model_dump()[key] == value for key, value in payload.items())


@pytest.mark.parametrize("schema,payload", [
    (ConversationModelPreferencePatch, {"parameter_values": {}}),
    (ConversationModelSelectionPatch, {"selected_model_id": 17}),
])
def test_retired_version_is_an_unsupported_field(schema, payload):
    with pytest.raises(ValidationError) as exc:
        schema.model_validate({**payload, "expected_version": 0})
    assert any(error["loc"] == ("expected_version",) and error["type"] == "extra_forbidden"
               for error in exc.value.errors())


def test_selection_still_requires_a_positive_model_id():
    with pytest.raises(ValidationError):
        ConversationModelSelectionPatch.model_validate({"selected_model_id": 0})
