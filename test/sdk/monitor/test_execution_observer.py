# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Root execution callbacks remain independent of telemetry and nested contexts."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from sdk.nexent.monitor.monitoring import (
    AgentRunMetadata,
    MonitoringConfig,
    MonitoringManager,
    get_agent_monitoring_context,
)


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(MonitoringManager, "_instance", None)
    monkeypatch.setattr(MonitoringManager, "_initialized", False)
    return MonitoringManager()


def test_disabled_capture_registers_one_root_and_preserves_child_context(manager):
    entries = []

    @contextmanager
    def observe(metadata):
        entries.append(metadata)
        yield replace(metadata, extra_metadata={"trajectory_id": "allocated"})

    manager.configure(
        MonitoringConfig(enable_telemetry=False, local_execution_observer=observe)
    )
    root = AgentRunMetadata(agent_id=7, conversation_id=123)
    with manager.start_agent_run(root):
        assert (
            get_agent_monitoring_context().extra_metadata["trajectory_id"]
            == "allocated"
        )
        with manager.start_agent_run(AgentRunMetadata(agent_id=8, conversation_id=123)):
            assert get_agent_monitoring_context().agent_id == 8
        assert get_agent_monitoring_context().agent_id == 7
    assert entries == [root] and get_agent_monitoring_context() is None


def test_non_execution_operations_do_not_allocate_a_root_and_errors_reset_context(
    manager,
):
    entries = []

    @contextmanager
    def observe(metadata):
        entries.append(metadata)
        yield metadata

    manager.configure(
        MonitoringConfig(enable_telemetry=False, local_execution_observer=observe)
    )
    with manager.start_agent_run(operation_name="agent.configure"):
        pass
    assert entries == []
    with pytest.raises(ValueError), manager.start_agent_run():
        raise ValueError("controlled Agent failure")
    assert get_agent_monitoring_context() is None
    with manager.start_agent_run():
        pass
    assert len(entries) == 2
