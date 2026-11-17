# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authentication boundary flags keep strict validation in the contract helper."""

import pytest

from contracts.configuration import parse_boolean


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("TRUE", True), ("false", False), ("FALSE", False)])
def test_boolean_flag_preserves_explicit_values_and_default(value, expected):
    assert parse_boolean(value, "GATEWAY_AUTH_ENABLED") is expected


@pytest.mark.parametrize("value", ["", "yes", "1", " false ", 1, True])
def test_invalid_flag_fails_without_echoing_input(value):
    with pytest.raises(ValueError, match="^GATEWAY_AUTH_ENABLED must be true or false$"):
        parse_boolean(value, "GATEWAY_AUTH_ENABLED")
