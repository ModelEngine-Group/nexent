# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["allowed", "revoked", "unavailable"])
async def test_shared_aidp_rechecks_actor_and_configured_scope(mocker, mode):
    from ext_components.aidp.services import aidp_access_service
    from management.services.agent.preparation import local_tool, tools
    from runtime.agentos import prepared_local_tool

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-signing-key")
    for name in ("AIDP_SERVER_URL", "AIDP_API_KEY", "AIDP_TENANT_ID"):
        mocker.patch.object(environment, name, "")
        mocker.patch.object(tools, name, "")

    row = {
        "tool_id": 7, "tool_instance_id": 19, "name": "aidp_search", "class_name": "AidpSearchTool",
        "source": "local", "description": "AIDP search", "usage": None, "inputs": None, "output_type": "string",
        "params": [{"name": "kds_list", "default": '["kb1","kb2"]'}, {"name": "api_key", "default": "obsolete-key"}],
        "instance_params": {},
    }
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    access = mocker.patch.object(aidp_access_service, "resolve_current_aidp_access")
    tool, = await tools.create_tool_config_list(8, "tenant-a", "user-a", version_no=3, portable_evaluation=True)
    access.assert_not_called()
    assert tool.params == {"kds_list": ["kb1", "kb2"]}
    binding = local_tool.export_local_tool(tool, [row], 8, 3, "tenant-a", "zh")
    encoded = binding.model_dump_json()
    for private in ("fixture-aidp.invalid", "fixture-aidp-key", "fixture-provider-tenant", "kb1", "obsolete-key"):
        assert private not in encoded

    mocker.patch.object(environment, "AIDP_SERVER_URL", "https://fixture-aidp.invalid")
    mocker.patch.object(environment, "AIDP_API_KEY", "fixture-aidp-key")
    mocker.patch.object(environment, "AIDP_TENANT_ID", "fixture-provider-tenant")
    access.return_value = SimpleNamespace(
        accessible_id_set={"kb1", "outside"} if mode == "allowed" else set(),
        name_to_id={"Allowed": "kb1", "Outside": "outside"} if mode == "allowed" else {},
        tenant_name_to_id={"Restricted": "kb2", "Another": "outside"},
    )
    if mode == "unavailable":
        access.side_effect = OSError("offline")
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    resource = SimpleNamespace(agent_id=8, version_no=3, tools=[binding])
    rebound = prepared_local_tool.materialize_local_tools(resource, ServicePrincipal("user-a", "tenant-a"), "zh")
    tool = rebound["aidp_search"]
    assert tool.params["kds_list"] == ["kb1", "kb2"]
    assert tool.params["api_key"] == "fixture-aidp-key"
    access.assert_called_once_with(
        server_url="https://fixture-aidp.invalid", api_key="fixture-aidp-key",
        user_id="user-a", tenant_id="tenant-a", aidp_tenant_id="fixture-provider-tenant",
    )
    assert tool.metadata["allowed_kds_set"] == (["kb1"] if mode == "allowed" else [])
    assert tool.metadata["kds_name_to_id_map"] == {
        "allowed": {"Allowed": "kb1", "Restricted": "kb2"},
        "revoked": {"Restricted": "kb2"}, "unavailable": {},
    }[mode]
