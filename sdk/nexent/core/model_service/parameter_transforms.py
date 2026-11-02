# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Executable versioned parameter conversions shared by validation and adapters."""

from types import MappingProxyType

from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, _json_copy


def _thinking_toggle(value):
    if type(value) is not bool:
        raise ParameterValidationError("PARAMETER_TRANSFORM_VALUE_INVALID")
    return "enabled" if value else "disabled"


_TRANSFORMS = MappingProxyType({
    ("identity_v1", 1): _json_copy,
    ("thinking_toggle_v1", 1): _thinking_toggle,
})


def parameter_transform_references():
    """Advertise only implementations available in this process."""
    return tuple(VersionedReference(ref=ref, version=version) for ref, version in _TRANSFORMS)


def transform_parameter(binding, value):
    """Transform a detached value; never infer a rule from provider or model names."""
    key = (binding["transform_ref"], binding["transform_version"])
    transform = _TRANSFORMS.get(key)
    if transform is None:
        raise ParameterValidationError("PARAMETER_TRANSFORM_UNREGISTERED")
    return transform(_json_copy(value))
