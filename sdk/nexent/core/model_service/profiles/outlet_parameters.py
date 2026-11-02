# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Single-location parameter storage, independent of database sessions and TOML."""

import math
from dataclasses import dataclass
from typing import Mapping

from nexent.core.model_service.profiles.parameter_rules import (
    CompiledParameterRules,
    validate_saved_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


DEDICATED_PARAMETER_KEYS = frozenset(
    {"temperature", "top_p", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens", "max_output_tokens"}
)
PARAMETER_COLUMNS = {key: "default_max_output_tokens" if key == "max_output_tokens" else key
                     for key in DEDICATED_PARAMETER_KEYS}


@dataclass
class StoredOutletParameters:
    """Detached fields to embed in a row, with no duplicate parameter values."""

    columns: dict[str, object]
    parameter_values: dict[str, object]
    explicit_null_parameters: list[str]


def _validate_column(key: str, value: object) -> None:
    if value is None:
        return
    valid = False
    if key in {"temperature", "top_p"}:
        try:
            valid = type(value) in {int, float} and math.isfinite(value)
            if valid and type(value) is int:
                valid = float(value) == value
        except OverflowError:
            valid = False
    elif key == "enable_thinking":
        valid = type(value) is bool
    elif key == "reasoning_effort":
        valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 30
    elif key == "reasoning_budget_tokens":
        valid = type(value) is int and -(2**31) <= value < 2**31
    elif key == "max_output_tokens":
        valid = type(value) is int and 0 < value < 2**31
    if not valid:
        raise ParameterValidationError("PARAMETER_COLUMN_INVALID", "/" + key)


def split_outlet_parameters(
    compiled: CompiledParameterRules,
    values: Mapping[str, object],
) -> StoredOutletParameters:
    """Split already resolved values; applying creation defaults is the caller's job."""
    validated = validate_saved_parameter_values(compiled, values)
    columns = {PARAMETER_COLUMNS[key]: None for key in sorted(DEDICATED_PARAMETER_KEYS)}
    remaining, nulls = {}, []
    for key, value in validated.items():
        if key in DEDICATED_PARAMETER_KEYS:
            _validate_column(key, value)
            columns[PARAMETER_COLUMNS[key]] = value
            if value is None:
                nulls.append(key)
        else:
            remaining[key] = value
    return StoredOutletParameters(columns, remaining, sorted(nulls))


def restore_outlet_parameters(
    compiled: CompiledParameterRules,
    *,
    columns: Mapping[str, object],
    parameter_values: Mapping[str, object],
    explicit_null_parameters: list[str],
) -> dict:
    """Restore exactly the saved key presence; reject corruption instead of repairing it."""
    if not isinstance(columns, Mapping) or set(columns) != set(PARAMETER_COLUMNS.values()):
        raise ParameterValidationError("PARAMETER_COLUMNS_INVALID")
    if (
        not isinstance(explicit_null_parameters, list)
        or any(type(key) is not str for key in explicit_null_parameters)
        or len(explicit_null_parameters) != len(set(explicit_null_parameters))
        or not set(explicit_null_parameters) <= DEDICATED_PARAMETER_KEYS
    ):
        raise ParameterValidationError("PARAMETER_NULL_MARKERS_INVALID")
    if not isinstance(parameter_values, Mapping) or DEDICATED_PARAMETER_KEYS & parameter_values.keys():
        raise ParameterValidationError("PARAMETER_STORAGE_DUPLICATE")
    values = dict(parameter_values)
    nulls = set(explicit_null_parameters)
    for key, column in PARAMETER_COLUMNS.items():
        value = columns[column]
        _validate_column(key, value)
        if key in nulls and value is not None:
            raise ParameterValidationError("PARAMETER_NULL_MARKERS_INVALID", "/" + key)
        if value is not None or key in nulls:
            values[key] = value
    return validate_saved_parameter_values(compiled, values)
