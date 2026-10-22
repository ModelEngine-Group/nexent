# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Contract tests for external-memory runtime configuration."""

from contracts.constants import memory as const_memory
from consts import const


def test_ac_p3_36_ingest_has_no_deployment_master_switch():
    assert not hasattr(const, "EXTERNAL_MEMORY_INGEST_ENABLED")


def test_ac_p3_37_agent_memory_units_are_allowed_for_external_ingest():
    assert "agent" in const_memory.EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES
