# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared SDK sampling defaults; a null value continues inheritance."""

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0


def resolve_sampling(temperature: float | None = None, top_p: float | None = None) -> dict[str, float]:
    """Resolve only absent values, preserving explicit zero and configured decimals."""
    return {
        "temperature": DEFAULT_TEMPERATURE if temperature is None else temperature,
        "top_p": DEFAULT_TOP_P if top_p is None else top_p,
    }
