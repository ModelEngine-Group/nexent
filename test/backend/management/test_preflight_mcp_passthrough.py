# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate Northbound MCP header routing before staging a prepared run."""

from copy import deepcopy

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, PreparedAgentRun
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.mcp_execution import build_mcp_tool
from management.db.agent import repository
from management.services.agent import mcp_passthrough
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls
from runtime.agentos import prepared_evaluation, prepared_mcp
from test.backend.app.test_agentos_prepared_evaluation import model_record
from test.backend.services.model_profile_helpers import stub_resolved_model_catalog
from infrastructure.agent_model_config import create_model_config_from_record
from nexent.core.agents.contracts.config import AgentConfig

ACTOR = ServicePrincipal("actor", "tenant-a")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)
BOUND = "https://bound.example/mcp"
OTHER = "https://other.example/mcp"


@pytest.fixture
def preparation(mocker):
    mocker.patch("contracts.constants.environment.JWT_SECRET", "fixture-mcp-key")
    row = {
        "tool_instance_id": 17, "name": "lookup", "class_name": "lookup", "origin_name": "lookup",
        "description": "Lookup", "inputs": None, "output_type": "object", "usage": "bound",
        "params": [], "instance_params": {},
    }
    server = {
        "mcp_id": 29, "mcp_name": "bound", "mcp_server": BOUND, "enabled": True,
        "authorization_token": "static-fixture", "custom_headers": {"X-Request-ID": "${X-Trace-ID}"},
    }
    unbound = {**server, "mcp_id": 30, "mcp_name": "other", "mcp_server": OTHER}
    model_row = model_record()
    model = create_model_config_from_record(model_row)
    agent = AgentConfig(agent_id=7, version_no=3, name="agent", description="", model_name=model.cite_name,
                        tools=[build_mcp_tool(row)])
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    mocker.patch.object(run_controls, "validate_agent_model_selection")
    mocker.patch.object(run_controls, "preflight_agent_turn_controls")
    agent_policy = mocker.patch.object(repository, "search_agent_info_by_agent_id", return_value={
        "allow_chat_metadata": True, "allow_mcp_header_passthrough": True,
    })
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(run, "create_model_config_list", return_value=[model])
    mocker.patch.object(run, "create_agent_config", side_effect=lambda **kw: agent.model_copy(deep=True))
    mocker.patch.object(evaluation_snapshot, "read_bound_mcp_tools", return_value=[row])
    mocker.patch.object(evaluation_snapshot, "read_mcp_execution_servers", return_value=[server, unbound])
    mocker.patch.object(mcp_passthrough, "read_mcp_execution_servers", return_value=[server, unbound])
    mocker.patch.object(prepared_mcp, "read_bound_mcp_tools", return_value=[row])
    mocker.patch.object(prepared_mcp, "read_mcp_execution_servers", return_value=[server, unbound])
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model_row)
    mocker.patch("management.services.agent.tool_identity.resolve_tool_user_context", return_value={})
    stub_resolved_model_catalog(mocker, model_row)
    return agent_policy


async def prepare(metadata, *, northbound=True):
    request = AgentRequest(
        agent_id=7, version_no=3, query="hello", conversation_id=42, metadata=metadata,
    )
    snapshot = await evaluation_snapshot.prepare_conversation_snapshot(
        request, REFERENCE, ACTOR.user_id, ACTOR.tenant_id,
        new_conversation=True, metadata_from_northbound=northbound,
    )
    return request, snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["global", "by_server", "disabled", "non_northbound", "business_only", None])
async def test_prepared_mcp_headers_are_request_scoped_and_keep_static_priority(preparation, mode):
    business = {"project": {"name": "fixture"}}
    override = {"Authorization": "request-fixture", "X-Trace-ID": "test-trace"}
    metadata = None if mode is None else deepcopy(business)
    if mode == "by_server":
        metadata["_mcp_headers_by_server"] = {BOUND: override}
    elif mode in {"global", "disabled", "non_northbound"}:
        metadata["_mcp_headers"] = override
    if mode == "disabled":
        preparation.return_value["allow_mcp_header_passthrough"] = False

    request, snapshot = await prepare(metadata, northbound=mode != "non_northbound")
    payload = PreparedAgentRun.model_validate_json(snapshot.model_dump_json())
    active = mode in {"global", "by_server"}
    assert payload.runtime_metadata == (business if mode is not None else {})
    assert bool(payload.mcp_header_metadata) is active
    assert request.metadata == metadata
    if active or mode == "disabled":
        preparation.assert_called_once_with(7, "tenant-a", 3)

    info = prepared_evaluation.prepare_run_snapshot(payload, ACTOR)
    host, = info.mcp_host
    assert host["url"] == BOUND and host["allowed_tools"] == {"lookup": "lookup"}
    assert host["headers"] == ({"Authorization": "static-fixture", "X-Request-ID": "test-trace", "x-trace-id": "test-trace"}
                               if active else {"Authorization": "static-fixture"})
    assert getattr(info, "runtime_metadata", None) == (business if mode is not None else {})


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [OTHER, "https://unspecified.example/mcp"])
async def test_preflight_rejects_registered_but_unbound_or_unknown_servers(preparation, target):
    with pytest.raises(AppException) as error:
        await prepare({"_mcp_headers_by_server": {target: {"X-Trace-ID": "test-trace"}}})

    assert error.value.error_code == ErrorCode.CHAT_MCP_HEADER_ROUTE_NOT_FOUND
    assert error.value.http_status == 400
    preparation.assert_not_called()


@pytest.mark.asyncio
async def test_prepared_snapshot_attaches_tenant_monitoring_catalog(preparation, mocker):
    catalog = [{"url": BOUND, "mcp_server_id": 29, "mcp_server_name": "bound", "mcp_server_type": "remote"}]
    mocker.patch("contracts.constants.environment.OPS_MONITORING_ENABLED", True)
    mocker.patch("contracts.constants.environment.LOCAL_MCP_SERVER", "http://local.invalid/mcp")
    mocker.patch("management.services.mcp.addressing.get_tenant_local_mcp_server",
                 side_effect=lambda tenant_id: f"http://local.invalid/mcp/{tenant_id}/sse")
    attach = mocker.patch("management.services.agent.monitoring_catalog.prepare_tenant_monitoring_catalog",
                          return_value=catalog)

    _, snapshot = await prepare(None)

    assert snapshot.model_dump().get("monitoring_mcp_servers") == catalog
    attach.assert_called_once_with("tenant-a", f"http://local.invalid/mcp/{ACTOR.tenant_id}/sse")


@pytest.mark.asyncio
async def test_prepared_snapshot_keeps_running_when_monitoring_catalog_is_absent(preparation, mocker):
    mocker.patch("contracts.constants.environment.OPS_MONITORING_ENABLED", True)
    mocker.patch("contracts.constants.environment.LOCAL_MCP_SERVER", None)
    attach = mocker.patch("management.services.agent.monitoring_catalog.prepare_tenant_monitoring_catalog",
                          return_value=None)

    _, snapshot = await prepare(None)

    assert snapshot is not None
    assert snapshot.model_dump().get("monitoring_mcp_servers") is None
    attach.assert_called_once_with("tenant-a", None)


@pytest.mark.asyncio
async def test_prepared_snapshot_skips_monitoring_catalog_when_disabled(preparation, mocker):
    mocker.patch("contracts.constants.environment.OPS_MONITORING_ENABLED", False)
    attach = mocker.patch("management.services.agent.monitoring_catalog.prepare_tenant_monitoring_catalog")

    _, snapshot = await prepare(None)

    assert snapshot is not None
    attach.assert_not_called()


@pytest.mark.asyncio
async def test_prepared_snapshot_returns_none_without_a_compiled_run(preparation, mocker):
    mocker.patch.object(run, "create_agent_run_info", return_value=None)

    _, snapshot = await prepare(None)

    assert snapshot is None
