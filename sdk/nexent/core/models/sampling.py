# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared SDK sampling defaults; a null value continues inheritance."""

DEFAULT_TEMPERATURE = None
DEFAULT_TOP_P = None


SAMPLING_FIELDS = ("temperature", "top_p")


def validate_sampling_value(field: str, value: object) -> None:
    """Accept an unset value or an explicit number in the supported range."""
    if value is None:
        return
    if field == "temperature":
        if type(value) not in (int, float) or not 0 <= value <= 2:
            raise ValueError("Temperature must be between 0 and 2. Clear it or enter a valid value.")
    elif type(value) not in (int, float) or not 0 < value <= 1:
        raise ValueError("Top P must be greater than 0 and at most 1. Clear it or enter a valid value.")


def without_unset_sampling(values):
    """Drop null sampling overrides so callers inherit from the next layer."""
    return {key: value for key, value in values.items() if key not in SAMPLING_FIELDS or value is not None}


def resolve_sampling(temperature: float | None = None, top_p: float | None = None) -> dict[str, float | None]:
    """Expose configured values without inventing service defaults."""
    return {
        "temperature": DEFAULT_TEMPERATURE if temperature is None else temperature,
        "top_p": top_p,
    }
