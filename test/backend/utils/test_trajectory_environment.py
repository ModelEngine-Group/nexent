# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trajectory query configuration does not require or consume signing keys."""

import runpy

import pytest


@pytest.mark.parametrize(
    "cursor_secret,legacy_key",
    [(None, None), ("", ""), ("cursor-key", None),
     (None, "legacy-key"), ("cursor-key", "legacy-key")],
)
def test_trajectory_configuration_ignores_removed_key_variables(
    monkeypatch, cursor_secret, legacy_key,
):
    monkeypatch.setenv("JWT_SECRET", "synthetic-jwt-key")
    for key, value in [("TRAJECTORY_CURSOR_SECRET", cursor_secret), ("TRAJECTORY_SIGNING_KEY", legacy_key)]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    config = runpy.run_module("contracts.constants.environment", run_name="trajectory_configuration_test")
    assert "TRAJECTORY_SIGNING_KEY" not in config
    assert "TRAJECTORY_CURSOR_SECRET" not in config
    assert config["JWT_SECRET"] == "synthetic-jwt-key"
