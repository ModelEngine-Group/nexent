# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the actual boundary configuration without a one-use parser abstraction."""

import runpy

import pytest


@pytest.fixture
def read_configuration(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)

    def read(value):
        if value is None:
            monkeypatch.delenv("GATEWAY_AUTH_ENABLED", raising=False)
        else:
            monkeypatch.setenv("GATEWAY_AUTH_ENABLED", value)
        return runpy.run_module("contracts.constants.environment", run_name="boundary_configuration_test")["GATEWAY_AUTH_ENABLED"]

    return read


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("TRUE", True), ("false", False), ("FALSE", False)])
def test_boolean_flag_preserves_explicit_values_and_default(read_configuration, value, expected):
    assert read_configuration(value) is expected


@pytest.mark.parametrize("value", ["", "yes", "1", " false ", "on"])
def test_invalid_flag_stops_configuration_instead_of_disabling_verification(read_configuration, value):
    with pytest.raises((ValueError, KeyError)):
        read_configuration(value)
