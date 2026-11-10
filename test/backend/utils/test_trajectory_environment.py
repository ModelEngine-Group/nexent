# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trajectory references use their dedicated deployment secret, never JWT keys."""

import runpy

import pytest


@pytest.mark.parametrize(
    "cursor_secret,legacy_key,expected",
    [(None, None, ""), ("", "", ""), ("cursor-key", None, "cursor-key"),
     (None, "legacy-key", "legacy-key"), ("cursor-key", "legacy-key", "cursor-key")],
)
def test_trajectory_cursor_secret_is_dedicated_and_matches_the_documented_name(
    monkeypatch, cursor_secret, legacy_key, expected,
):
    monkeypatch.setenv("JWT_SECRET", "synthetic-jwt-key")
    for key, value in [("TRAJECTORY_CURSOR_SECRET", cursor_secret), ("TRAJECTORY_SIGNING_KEY", legacy_key)]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    config = runpy.run_module("contracts.constants.environment", run_name="trajectory_configuration_test")
    assert config["TRAJECTORY_SIGNING_KEY"] == expected
    assert config["JWT_SECRET"] == "synthetic-jwt-key"
