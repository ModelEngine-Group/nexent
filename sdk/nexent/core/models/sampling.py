# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared SDK sampling defaults; a null value continues inheritance."""

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = None


def validate_top_p(value: object) -> None:
    """Accept an unset value or an explicit number in the protocol range."""
    if value is not None and (type(value) not in (int, float) or not 0 < value <= 1):
        raise ValueError("Top P must be greater than 0 and at most 1. Clear it or enter a valid value.")


def resolve_sampling(temperature: float | None = None, top_p: float | None = None) -> dict[str, float | None]:
    """Resolve only absent values, preserving stored values for display."""
    return {
        "temperature": DEFAULT_TEMPERATURE if temperature is None else temperature,
        "top_p": top_p,
    }
