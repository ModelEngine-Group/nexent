# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Parameter controls require explicit, registered and nonoverlapping body bindings."""

import pytest
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.parameter_bindings import (
    validate_parameter_bindings,
)
from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError

IDENTITY = VersionedReference(ref="identity_v1", version=1)


def rule(key="temperature", path="/temperature", **changes):
    declaration = {
        "key": key,
        "schema": {"type": "number"},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "sampling",
        "owner": "provider",
        "source": {"ref": "fixture"},
        "api_binding": {
            "path": path,
            "transform_ref": "identity_v1",
            "transform_version": 1,
        },
    }
    declaration.update(changes)
    return declaration


def validate(declarations, transforms=(IDENTITY,), **options):
    return validate_parameter_bindings(
        compile_parameter_rules(declarations), transforms, **options
    )


def test_registered_binding_is_immutable_and_detached():
    declaration = rule()
    bindings = validate([declaration])
    declaration["api_binding"]["path"] = "/different"
    assert bindings["temperature"]["path"] == "/temperature"
    with pytest.raises(TypeError):
        bindings["temperature"]["path"] = "/different"


@pytest.mark.parametrize(
    "visible,editable", [(True, True), (True, False), (False, True)]
)
def test_exposed_control_cannot_be_declared_without_binding(visible, editable):
    with pytest.raises(ParameterValidationError, match="PARAMETER_BINDING_MISSING"):
        validate([rule(api_binding=None, visible=visible, editable=editable)])


def test_hidden_readonly_metadata_does_not_create_request_field():
    assert dict(validate([rule(api_binding=None, visible=False, editable=False)])) == {}


@pytest.mark.parametrize(
    "binding",
    [
        {"path": "/temperature", "transform_ref": "identity_v1"},
        {
            "path": "/temperature",
            "transform_ref": "identity_v1",
            "transform_version": True,
        },
        {
            "path": "/temperature",
            "transform_ref": "identity_v1",
            "transform_version": 0,
        },
        {
            "path": "/temperature",
            "transform_ref": "identity_v1",
            "transform_version": 1,
            "script": "secret-body",
        },
        {"path": "temperature", "transform_ref": "identity_v1", "transform_version": 1},
        {"path": "/bad~escape", "transform_ref": "identity_v1", "transform_version": 1},
    ],
)
def test_invalid_binding_has_value_free_field_diagnostic(binding):
    with pytest.raises(
        ParameterValidationError, match="PARAMETER_BINDING_INVALID"
    ) as captured:
        validate([rule(api_binding=binding)])
    assert captured.value.path == "/parameter_rules/temperature/api_binding"
    assert "secret-body" not in str(captured.value)


def test_reference_must_match_registered_name_and_version():
    for transforms in [(), (VersionedReference(ref="identity_v1", version=2),)]:
        with pytest.raises(
            ParameterValidationError, match="PARAMETER_TRANSFORM_UNREGISTERED"
        ):
            validate([rule()], transforms)


@pytest.mark.parametrize(
    "path",
    [
        "/model",
        "/messages/0",
        "/tools",
        "/tool_choice",
        "/stream",
        "/stream_options/include_usage",
    ],
)
def test_parameters_cannot_overwrite_runtime_owned_fields(path):
    with pytest.raises(ParameterValidationError, match="RESERVED_API_PATH"):
        validate([rule(path=path)])


def test_adapter_owned_field_is_protected():
    with pytest.raises(ParameterValidationError, match="RESERVED_API_PATH"):
        validate([rule(path="/options/auth")], protected_paths=["/options"])


@pytest.mark.parametrize(
    "left,right",
    [("/options", "/options/effort"), ("/effort", "/effort"), ("/a~1b", "/a~1b/value")],
)
def test_duplicate_and_parent_child_bindings_are_rejected(left, right):
    with pytest.raises(ParameterValidationError, match="PARAMETER_BINDING_CONFLICT"):
        validate([rule("first", left), rule("second", right)])


def test_distinct_escaped_fields_and_siblings_remain_distinct():
    bindings = validate(
        [rule("first", "/a~1b"), rule("second", "/a/b"), rule("third", "/a/c")]
    )
    assert set(bindings) == {"first", "second", "third"}
