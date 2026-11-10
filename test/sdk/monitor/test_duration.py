# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Elapsed observations distinguish a measured zero from invalid clock values."""

import pytest


@pytest.mark.parametrize("elapsed,expected", [(0, 0), (0.125, 125), (2, 2000)])
def test_monotonic_duration_units_and_zero(elapsed, expected):
    from nexent.monitor.duration import duration_attributes

    assert duration_attributes(10, 10 + elapsed) == {"nexent.duration_ms": expected}


@pytest.mark.parametrize(
    "start,end",
    [
        (10, 9),
        (None, 11),
        (True, 11),
        (10, False),
        (10, float("nan")),
        (10, float("inf")),
        (float("inf"), 11),
        ("10", 11),
        (10**1000, 11),
    ],
)
def test_invalid_or_unavailable_clock_is_unknown(start, end):
    from nexent.monitor.duration import duration_attributes

    assert duration_attributes(start, end) == {
        "nexent.availability.duration_ms": "not_captured"
    }
