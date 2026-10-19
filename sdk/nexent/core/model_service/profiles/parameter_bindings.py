# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate explicit body bindings against registered parameter transforms."""

from typing import Mapping, Sequence

from pydantic import ValidationError

from nexent.core.model_service.profiles._models_dev.reader import _freeze
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.parameter_rules import CompiledParameterRules
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.request_parameters import _CONTROLLED_PATHS, _overlap, _tokens


def validate_parameter_bindings(
    rules: CompiledParameterRules,
    registered_transforms: Sequence[VersionedReference],
    *,
    protected_paths: Sequence[str] = (),
) -> Mapping[str, Mapping[str, object]]:
    """Return immutable declarations; this does not render or send model requests."""
    protected = [_tokens(path) for path in (*_CONTROLLED_PATHS, *protected_paths)]
    paths, bindings = [], {}
    for rule in rules.declarations:
        location = "/parameter_rules/" + rule["key"].replace("~", "~0").replace("/", "~1") + "/api_binding"
        binding = rule.get("api_binding")
        if binding is None:
            if rule["visible"] or rule["editable"]:
                raise ParameterValidationError("PARAMETER_BINDING_MISSING", location)
            continue
        if not isinstance(binding, dict) or set(binding) != {"path", "transform_ref", "transform_version"}:
            raise ParameterValidationError("PARAMETER_BINDING_INVALID", location)
        try:
            reference = VersionedReference.model_validate(
                {
                    "ref": binding["transform_ref"],
                    "version": binding["transform_version"],
                }
            )
        except ValidationError:
            raise ParameterValidationError("PARAMETER_BINDING_INVALID", location) from None
        if reference not in registered_transforms:
            raise ParameterValidationError("PARAMETER_TRANSFORM_UNREGISTERED", location)
        try:
            tokens = _tokens(binding["path"])
        except ParameterValidationError:
            raise ParameterValidationError("PARAMETER_BINDING_INVALID", location) from None
        if any(_overlap(tokens, path) for path in protected):
            raise ParameterValidationError("RESERVED_API_PATH", location)
        if any(_overlap(tokens, path) for path in paths):
            raise ParameterValidationError("PARAMETER_BINDING_CONFLICT", location)
        paths.append(tokens)
        bindings[rule["key"]] = binding
    return _freeze(bindings)
