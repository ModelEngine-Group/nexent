# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate monotonic elapsed observations without turning clock failures into zero."""

import math


def duration_attributes(started, ended):
    """Return a measured millisecond value or an explicit unavailable marker."""
    if type(started) in (int, float) and type(ended) in (int, float):
        try:
            elapsed_ms = float(ended - started) * 1000
            if math.isfinite(elapsed_ms) and elapsed_ms >= 0:
                return {"nexent.duration_ms": elapsed_ms}
        except OverflowError:
            pass
    return {"nexent.availability.duration_ms": "not_captured"}
