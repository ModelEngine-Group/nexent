# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import sys

import pytest

from infrastructure.system_configuration.catalog import DEFAULT_CATALOG


@pytest.fixture(autouse=True)
def _nl2agent_configuration_snapshot(monkeypatch):
    """Resource-flow unit tests do not start a configuration worker."""
    flow = sys.modules.get("services.nl2agent_resource_flow")
    if flow is not None and hasattr(flow, "get_config_snapshot"):
        snapshot = DEFAULT_CATALOG.build_snapshot(DEFAULT_CATALOG.defaults)
        monkeypatch.setattr(flow, "get_config_snapshot", lambda: snapshot)
