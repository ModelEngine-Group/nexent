# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict sampling is checked once against canonical outlet rules."""

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.conversation.model_preferences import merge_model_preferences
from management.services.model.profiles import build_outlet_draft
from test.backend.services.test_model_profile_service import draft_request
from management.services.agent.stream import sampling_configuration_error_payload, safe_agent_stream_error_chunk


@pytest.mark.parametrize("field,maximum", [("temperature", 2), ("top_p", 1)])
def test_su_ac_05_sampling_presence_bounds_zero_and_explicit_null(field, maximum):
    profile, _ = build_outlet_draft(draft_request(), "tenant")
    data = profile.model_dump()
    next(rule for rule in data["parameter_rules"] if rule["key"] == field)["schema"].update(minimum=0, maximum=maximum)
    profile = type(profile).model_validate(data)
    for value in [0, 0.7, maximum, None]:
        assert merge_model_preferences(profile, {field: value}).parameter_values[field] == value
    for invalid in [-0.1, maximum + 0.1, True, "0.7", float("nan"), float("inf")]:
        with pytest.raises(ModelOutletValidationError):
            merge_model_preferences(profile, {field: invalid})


def test_sampling_errors_are_actionable_and_sanitized_through_wrapped_causes():
    from nexent.core.models.openai_llm import SamplingConfigurationError
    inner = SamplingConfigurationError('provider-secret detail')
    outer = RuntimeError('private prompt'); outer.__cause__ = inner
    payload = sampling_configuration_error_payload(outer)
    assert payload['code'] == 'MODEL_SAMPLING_CONFIG_INVALID'
    chunk = safe_agent_stream_error_chunk(outer)
    assert 'MODEL_SAMPLING_CONFIG_INVALID' in chunk and 'provider-secret' not in chunk and 'private prompt' not in chunk
    assert sampling_configuration_error_payload(ValueError('unrelated')) is None
