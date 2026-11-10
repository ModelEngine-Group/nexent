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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["revoked", "changed", "missing", "non_workbench"])
async def test_workbench_mounts_tenant_catalog_aidp_with_signed_scope(mocker, mode):
    from fastapi import HTTPException

    from contracts.agent import AgentRequest, WorkbenchSessionConfig
    from ext_components.aidp.services import aidp_access_service
    from management.services.agent import workbench
    from management.services.agent.preparation import local_tool, tools
    from management.services.knowledge_base import mount, scope
    from runtime.agentos import prepared_local_tool

    mocker.patch.object(environment, "JWT_SECRET", "fixture-signing-key")
    mocker.patch.object(environment, "AIDP_SERVER_URL", "https://provider.invalid")
    mocker.patch.object(environment, "AIDP_API_KEY", "fixture-key")
    mocker.patch.object(environment, "AIDP_TENANT_ID", "fixture-provider")
    mocker.patch.object(mount, "ENABLE_AIDP_KNOWLEDGE", True)
    row = {
        "tool_id": 7, "name": "aidp_search", "class_name": "AidpSearchTool", "source": "local",
        "description": "AIDP search", "usage": None, "inputs": None, "output_type": "string",
        "is_available": True, "instance_params": {},
        "params": [{"name": "kds_list", "default": '["old"]'},
                   {"name": "top_k", "type": "integer", "default": 10},
                   {"name": "search_method", "type": "string", "default": "hybrid_search"},
                   {"name": "api_key", "default": "obsolete-key"}],
    }
    config = WorkbenchSessionConfig(mode="generic_chat", knowledge_scope={
        "aidp": {"mode": "override", "kds_ids": ["kb1", "kb2", "private"]},
        "retrieval_config": {"top_k": 7, "search_method": "full_text_search"},
    })
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=8, version_no=3)), root_skills=())
    mocker.patch.object(workbench, "resolve_workbench_config", return_value=(config, plan))
    mocker.patch.object(mount, "query_all_tools", return_value=[row])
    mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
        {"agent_name": "root", "tools": []}, {"agent_name": "child", "tools": [row]},
    ])
    mocker.patch.object(scope, "_resolve_aidp_access_snapshot", return_value=SimpleNamespace(
        accessible_id_set={"kb1", "kb2"}, name_to_id={"One": "kb1", "Two": "kb2"},
    ))
    request = AgentRequest(query="query", entrypoint="workbench", workbench=config)
    prepared = workbench.prepare_portable_workbench(request, None, "user-a", "tenant-a")
    assert prepared.knowledge.aidp_kds_ids == ["kb1", "kb2"]
    assert prepared.knowledge.warnings == [{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE", "source": "aidp", "count": 1}]
    assert "child" not in prepared.knowledge.tool_params.agents
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    tool, = await tools.create_tool_config_list(
        8, "tenant-a", "user-a", version_no=3, tool_params=prepared.knowledge.tool_params,
        runtime_knowledge_tools=prepared.knowledge_tools, portable_evaluation=True,
    )
    mocker.patch.object(local_tool, "read_shared_aidp_catalog_tool", return_value=row)
    binding = local_tool.export_scoped_shared_aidp(tool, 8, 3, "tenant-a", "zh")
    assert binding.version == "3"
    assert binding.parameters["options"] == {
        "kds_list": ["kb1", "kb2"], "top_k": 7, "search_method": "full_text_search",
    }
    encoded = binding.model_dump_json()
    for private in ("private", "obsolete-key", "fixture-key", "fixture-provider", "provider.invalid", "old"):
        assert private not in encoded
    current = None if mode == "missing" else row
    if mode == "changed":
        current = {**row, "description": "New revision"}
    catalog = mocker.patch.object(prepared_local_tool, "read_shared_aidp_catalog_tool", return_value=current)
    access = mocker.patch.object(aidp_access_service, "resolve_current_aidp_access", return_value=SimpleNamespace(
        accessible_id_set={"kb1", "outside"}, name_to_id={"One": "kb1"}, tenant_name_to_id={},
    ))
    actor = ServicePrincipal("user-a", "tenant-a")
    resource = SimpleNamespace(agent_id=8, version_no=3, tools=[binding])
    if mode == "non_workbench":
        with pytest.raises(ValueError, match="Unsupported local SDK tool binding"):
            prepared_local_tool.materialize_local_tools(resource, actor, "zh")
        catalog.assert_not_called()
    elif mode in {"changed", "missing"}:
        with pytest.raises(HTTPException) as error:
            prepared_local_tool.materialize_local_tools(resource, actor, "zh", allow_scoped_aidp=True)
        assert error.value.status_code == (409 if mode == "changed" else 404)
    else:
        rebound = prepared_local_tool.materialize_local_tools(resource, actor, "zh", allow_scoped_aidp=True)["aidp_search"]
        assert rebound.metadata["allowed_kds_set"] == ["kb1"]
        assert rebound.params["api_key"] == "fixture-key"
        assert rebound.params["top_k"] == 7
        access.assert_called_once_with(
            server_url="https://provider.invalid", api_key="fixture-key", user_id="user-a",
            tenant_id="tenant-a", aidp_tenant_id="fixture-provider",
        )
    if mode != "revoked":
        access.assert_not_called()


@pytest.mark.asyncio
async def test_native_scope_exports_only_authorized_child_aidp_and_runtime_rechecks(mocker, tmp_path):
    from fastapi import HTTPException

    from contracts.agent import AgentRequest
    from contracts.agentos import PreparedConversationScope
    from contracts.errors.exceptions import ValidationError
    from ext_components.aidp.services import aidp_access_service
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation import evaluation_snapshot, local_tool, tools
    from management.services.knowledge_base import scope
    from nexent.core.agents.agent_model import AgentConfig
    from runtime.agentos import prepared_evaluation, prepared_local_tool
    from test.backend.app.test_agentos_prepared_evaluation import model_record

    mocker.patch.object(environment, "JWT_SECRET", "fixture-signing-key")
    mocker.patch.object(environment, "AIDP_SERVER_URL", "https://provider.invalid")
    mocker.patch.object(environment, "AIDP_API_KEY", "fixture-key")
    mocker.patch.object(environment, "AIDP_TENANT_ID", "fixture-provider")
    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    mocker.patch.object(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    row = {
        "tool_id": 7, "name": "aidp_search", "class_name": "AidpSearchTool", "source": "local",
        "description": "AIDP search", "usage": None, "inputs": None, "output_type": "string",
        "params": [{"name": "kds_list", "default": '["original"]'}], "instance_params": {},
    }
    mocker.patch.object(scope, "resolve_root_version", return_value=3)
    mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
        {"agent_id": 8, "version_no": 3, "agent_name": "root", "tools": []},
        {"agent_id": 9, "version_no": 4, "agent_name": "child", "tools": [row]},
    ])
    mocker.patch.object(scope, "_resolve_aidp_access_snapshot", return_value=SimpleNamespace(
        accessible_id_set={"kb1", "kb2"}, name_to_id={"One": "kb1", "Two": "kb2"},
    ))
    request = AgentRequest(query="query", agent_id=8, knowledge_scope={
        "local": {"mode": "disabled"}, "aidp": {"mode": "override", "kds_ids": ["kb1", "kb2", "denied"]},
    }, tool_params={"agents": {"child": {"tools": {"aidp_search": {"kds_list": ["forged"]}}}}})
    with pytest.raises(ValidationError, match="unavailable or inaccessible"):
        evaluation_snapshot.prepare_native_knowledge(request, {}, "user-a", "tenant-a")
    prepared = evaluation_snapshot.prepare_native_knowledge(request, None, "user-a", "tenant-a")
    assert prepared.authorized_tools[(9, 4)] == {"aidp_search": {"kds_list": ["kb1", "kb2"]}}
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "child"})
    options = {
        "tool_params": request.tool_params, "portable_evaluation": True,
        "authorized_knowledge_tools": prepared.authorized_tools,
    }
    with pytest.raises(ValidationError, match="configuration changed"):
        await tools.create_tool_config_list(9, "tenant-a", "user-a", version_no=5, **options)
    tool, = await tools.create_tool_config_list(9, "tenant-a", "user-a", version_no=4, **options)
    mocker.patch.object(local_tool, "read_shared_aidp_catalog_tool", return_value=row)
    catalog = mocker.patch.object(prepared_local_tool, "read_shared_aidp_catalog_tool", return_value=row)
    bound = mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[])
    mocker.patch.object(prepared_local_tool, "read_skill_derived_local_tools", return_value=[])
    access = mocker.patch.object(aidp_access_service, "resolve_current_aidp_access", return_value=SimpleNamespace(
        accessible_id_set={"kb1", "outside"}, name_to_id={"One": "kb1"}, tenant_name_to_id={},
    ))
    model = model_record(model_id=11)
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[model])
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model)
    selected = create_model_config_from_record(model)
    child = AgentConfig(agent_id=9, version_no=4, name="child", description="", model_name=selected.cite_name, tools=[tool])
    root = AgentConfig(
        agent_id=8, version_no=3, name="root", description="", model_name=selected.cite_name, tools=[], worker_agents=[child],
    )
    snapshot = evaluation_snapshot.export_snapshot(
        root, [selected], "query", None, tenant_id="tenant-a", conversation_id=42, language="zh",
        prepared_conversation=PreparedConversationScope(conversation_id=42, run_id="a" * 32, native_knowledge=True),
    )
    assert snapshot is not None
    for private in ("forged", "denied", "original", "fixture-key"):
        assert private not in snapshot.model_dump_json()
    actor = ServicePrincipal("user-a", "tenant-a")
    with pytest.raises(HTTPException) as error:
        prepared_evaluation.prepare_run_snapshot(snapshot.model_copy(update={"native_knowledge": None}), actor)
    assert error.value.status_code == 422
    catalog.assert_not_called()
    with pytest.raises(HTTPException) as unbound:
        prepared_evaluation.prepare_run_snapshot(snapshot, actor)
    assert unbound.value.status_code == 404
    catalog.assert_not_called()
    access.assert_not_called()

    bound.return_value = [row]
    runtime = prepared_evaluation.prepare_run_snapshot(snapshot, actor)
    mounted = runtime.agent_config.worker_agents[0].tools[0]
    assert mounted.params["api_key"] == "fixture-key" and mounted.metadata["allowed_kds_set"] == ["kb1"]
    catalog.assert_called_once_with(7, "tenant-a")
    access.assert_called_once()
