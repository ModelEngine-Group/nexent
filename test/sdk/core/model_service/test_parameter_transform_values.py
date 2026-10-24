# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pure transform domains and copy semantics, independent of persistence or HTTP."""

import pytest
from nexent.core.model_service.parameter_transforms import transform_parameter
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


def binding(ref="thinking_toggle_v1", version=1):
    return {"path": "/thinking/type", "transform_ref": ref, "transform_version": version}


@pytest.mark.parametrize("value,expected", [(True, "enabled"), (False, "disabled")])
def test_boolean_thinking_transform_has_no_truthiness_coercion(value, expected):
    assert transform_parameter(binding(), value) == expected


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
def test_non_boolean_thinking_value_is_rejected(value):
    with pytest.raises(ParameterValidationError) as error:
        transform_parameter(binding(), value)
    assert error.value.category == "PARAMETER_TRANSFORM_VALUE_INVALID"


def test_unknown_transform_version_is_not_approximated():
    with pytest.raises(ParameterValidationError) as error:
        transform_parameter(binding(version=2), True)
    assert error.value.category == "PARAMETER_TRANSFORM_UNREGISTERED"


def test_identity_result_is_detached():
    source = {"items": [1, False]}
    result = transform_parameter(binding(ref="identity_v1"), source)
    result["items"].append("changed")
    assert source == {"items": [1, False]}

