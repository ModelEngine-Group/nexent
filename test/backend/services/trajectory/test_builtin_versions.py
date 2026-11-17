# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Presentation versions are derived from protected identities without rewriting facts."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from ops.services.trajectory.primitives import QueryError


@pytest.mark.parametrize("version", [None, 0, 4])
def test_builtin_records_use_v1_without_changing_regular_or_unknown_agents(version):
    from ops.services.trajectory.versions import apply_builtin_versions

    catalog = Mock()
    catalog.builtin_agent_ids.return_value = {("t", "7")}
    items = [
        {"tenant_id": "t", "root_agent_id": "7", "root_agent_version_no": version,
         "root_agent_version_name": "Actual release"},
        {"tenant_id": "t", "root_agent_id": "8", "root_agent_version_no": version,
         "root_agent_name": "NL2Agent"},
        {"tenant_id": "other", "root_agent_id": "7", "root_agent_version_no": version},
    ]
    untouched = deepcopy(items[1:])
    apply_builtin_versions(catalog, ["t", "other"], items)
    assert items[0]["root_agent_version_no"] == 1
    assert items[0]["root_agent_version_name"] == "V1"
    assert items[1:] == untouched
    catalog.builtin_agent_ids.assert_called_once_with(["t", "other"], {"7", "8"})


def test_builtin_node_version_does_not_replace_archived_attributes_or_model_tool_versions():
    from ops.services.trajectory.versions import apply_builtin_versions

    catalog = Mock()
    catalog.builtin_agent_ids.return_value = {("t", "7")}
    items = [
        {"kind": "agent", "_agent_id": "7", "attributes": {"agent.id": "7", "agent.version_no": "0"},
         "agent_version_no": 0},
        {"kind": "agent", "_agent_id": "8", "attributes": {"agent.id": "8"}, "agent_version_no": 0},
        {"kind": "model", "attributes": {"agent.id": "7"}, "agent_version_no": None},
        {"kind": "tool", "attributes": {"agent.id": "7"}, "agent_version_no": None},
    ]
    original = deepcopy(items)
    apply_builtin_versions(catalog, ["t"], items, nodes=True)
    assert items[0]["agent_version_no"] == 1
    assert items[0]["attributes"] == original[0]["attributes"]
    assert items[1:] == original[1:]


@pytest.mark.parametrize("agent_id", [None, True, "runtime-id", "-1", "1.0", "9" * 100, "７"])
def test_non_persisted_identities_do_not_query_or_change_versions(agent_id):
    from ops.services.trajectory.versions import apply_builtin_versions

    catalog = Mock()
    item = {"root_agent_id": agent_id, "root_agent_version_no": 0}
    apply_builtin_versions(catalog, ["t"], [item])
    assert item["root_agent_version_no"] == 0
    catalog.builtin_agent_ids.assert_not_called()


def test_identity_lookup_failure_is_not_reported_as_a_builtin_version():
    from ops.services.trajectory.versions import apply_builtin_versions

    catalog = Mock()
    catalog.builtin_agent_ids.side_effect = QueryError("query_failed", 503)
    item = {"root_agent_id": "7", "root_agent_version_no": 0}
    with pytest.raises(QueryError, match="query_failed"):
        apply_builtin_versions(catalog, ["t"], [item])
    assert item["root_agent_version_no"] == 0


def test_file_nodes_and_cached_details_use_builtin_display_version(mocker):
    from contextlib import nullcontext

    from ops.services.trajectory.primitives import ReferenceStore
    from ops.services.trajectory.service import TrajectoryService
    from test_nodes import request, span

    catalog = Mock()
    catalog.builtin_agent_ids.return_value = {("t", "7")}
    service = TrajectoryService(Mock(), catalog, ReferenceStore())
    run = {"root_agent_id": "7", "confirmed_bytes": 1, "capture_state": "ready"}
    service.archive.opened = Mock(side_effect=lambda *args: nullcontext((0, {}, run)))
    mocker.patch.object(service, "binding", return_value={"scope": "authorized-execution"})
    root = span("root")
    root["attributes"].append({"key": "agent.version_no", "value": {"intValue": "0"}})
    child = span("child", "root", **{"agent.id": "8"})
    child["attributes"].append({"key": "agent.version_no", "value": {"intValue": "0"}})
    reader = mocker.patch("ops.services.trajectory.service.JSONReader")
    reader.return_value.requests.return_value = request(root, child)
    actor, row, budget = Mock(), {"tenant_id": "t", "conversation_id": "1"}, Mock()
    first = service.load(actor, row, "run", budget)
    second = service.load(actor, row, "run", budget)
    by_id = {node["id"]: node for node in first[0]}
    assert by_id["root"]["agent_version_no"] == 1
    assert by_id["root"]["agent_version_name"] == "V1"
    assert by_id["child"]["agent_version_no"] == 0
    assert first == second
    assert root["attributes"][-1]["value"]["intValue"] == "0"
    catalog.builtin_agent_ids.assert_called_once_with(["t"], {"7", "8"})
    reader.assert_called_once()
