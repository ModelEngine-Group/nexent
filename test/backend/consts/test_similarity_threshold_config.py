# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Similarity configuration retains its default, bounds and error messages."""

import pytest

from contracts.configuration import parse_similarity_threshold


@pytest.mark.parametrize("raw,expected", [(None, 0.5), ("0.01", 0.01), ("1", 1.0)])
def test_valid_similarity_threshold(raw, expected):
    assert parse_similarity_threshold(raw, "SIMILARITY", 0.5) == expected


@pytest.mark.parametrize("raw", ["0", "-0.1", "nan", "inf", "invalid", ""])
def test_invalid_positive_similarity_threshold(raw):
    with pytest.raises(ValueError, match="^SIMILARITY must be a positive number$"):
        parse_similarity_threshold(raw, "SIMILARITY", 0.5)


@pytest.mark.parametrize("raw,default", [("1.01", 0.5), (None, 1.01)])
def test_similarity_threshold_above_one(raw, default):
    with pytest.raises(ValueError, match="^SIMILARITY must be at most 1$"):
        parse_similarity_threshold(raw, "SIMILARITY", default)
