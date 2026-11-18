# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared test fixtures for injecting immutable system configuration values."""

from management.configuration.catalog import DEFAULT_CATALOG

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def system_config_snapshot(**changes):
    return DEFAULT_CATALOG.build_snapshot({**EXPECTED_DEFAULTS, **changes})
