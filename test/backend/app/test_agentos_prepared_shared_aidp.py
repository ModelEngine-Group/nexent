# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import sys
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pytest

from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from test.backend.services.model_profile_helpers import stub_resolved_model_catalog


def test_shared_aidp_permissions_import_without_management(monkeypatch):
    monkeypatch.setitem(sys.modules, "management.db.identity", None)
    backend = Path(__file__).resolve().parents[3] / "backend"
    service = backend / "ext_components/aidp/services/aidp_permission_service.py"

    permission_service = run_path(str(service))

    assert callable(permission_service["intersect_accessible_kbs_with_name_map"])


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
    request = AgentRequest(
        query="query", entrypoint="workbench", workbench=config,
        tool_params={"agents": {"root": {"tools": {"aidp_search": {
            "top_k": 7, "search_method": "full_text_search",
        }}}}},
    )
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
@pytest.mark.parametrize("debug", [False, True])
async def test_native_scope_exports_only_authorized_child_aidp_and_runtime_rechecks(mocker, tmp_path, debug):
    from fastapi import HTTPException
    from pydantic import ValidationError as PayloadValidationError

    from contracts.agent import AgentRequest
    from contracts.agentos import PreparedConversationScope, PreparedEphemeralRun
    from contracts.errors.exceptions import ValidationError
    from ext_components.aidp.services import aidp_access_service
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation import evaluation_snapshot, local_tool, tools
    from management.services.knowledge_base import scope
    from nexent.core.agents.contracts.config import AgentConfig
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
    request = AgentRequest(query="query", agent_id=8, is_debug=debug, knowledge_scope={
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
    stub_resolved_model_catalog(mocker, model)
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model)
    selected = create_model_config_from_record(model)
    child = AgentConfig(agent_id=9, version_no=4, name="child", description="", model_name=selected.cite_name, tools=[tool])
    root = AgentConfig(
        agent_id=8, version_no=3, name="root", description="", model_name=selected.cite_name, tools=[], worker_agents=[child],
    )
    snapshot = evaluation_snapshot.export_snapshot(
        root, [selected], "query", None, tenant_id="tenant-a", conversation_id=None if debug else 42, language="zh",
        prepared_conversation=None if debug else PreparedConversationScope(
            conversation_id=42, run_id="a" * 32, native_knowledge=True,
        ),
    )
    assert snapshot is not None
    if debug:
        fields = snapshot.model_dump(exclude={"conversation_id"})
        with pytest.raises(PayloadValidationError, match="only for debug"):
            PreparedEphemeralRun(**fields, run_id="a" * 32, native_knowledge=True)
        snapshot = PreparedEphemeralRun(**fields, run_id="a" * 32, debug=True, native_knowledge=True)
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
    assert runtime.conversation_id == (None if debug else 42)
    mounted = runtime.agent_config.worker_agents[0].tools[0]
    assert mounted.params["api_key"] == "fixture-key" and mounted.metadata["allowed_kds_set"] == ["kb1"]
    catalog.assert_called_once_with(7, "tenant-a")
    access.assert_called_once()


@pytest.mark.parametrize("platform_allowed", [False, True])
@pytest.mark.parametrize("origin", ["SYSTEM", "PERSISTED"])
@pytest.mark.parametrize("tenant_binding", [False, True])
def test_stored_platform_aidp_requires_workbench_run(mocker, platform_allowed, origin, tenant_binding):
    mocker.patch.object(environment, "JWT_SECRET", "fixture-signing-key")
    from fastapi import HTTPException

    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import evaluation_snapshot
    from management.services.agent.preparation.local_tool import export_local_tool
    from nexent.core.agents.contracts.config import AgentConfig
    from runtime.agentos import prepared_local_tool

    row = {
        "tool_id": 7, "tool_instance_id": 19, "name": "aidp_search", "class_name": "AidpSearchTool",
        "source": "local", "description": "AIDP search", "usage": None, "inputs": None, "output_type": "string",
        "params": [{"name": "kds_list", "default": '["kb1"]'}], "instance_params": {},
    }
    tool = build_local_tool(row, "en", None, None)
    binding = export_local_tool(tool, [row], 8, 3, "tenant-a", "en")
    resource = SimpleNamespace(agent_id=8, version_no=3, origin=origin, tools=[binding])
    actor = ServicePrincipal("user-a", "tenant-a")
    tenant_rows = [row] if tenant_binding else []
    catalog = mocker.patch.object(evaluation_snapshot, "read_bound_local_tools", side_effect=lambda *_: tenant_rows.copy())
    export_platform = mocker.patch.object(
        evaluation_snapshot, "read_workbench_default_aidp_tools", return_value=[row],
    )
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", side_effect=lambda *_: tenant_rows.copy())
    platform = mocker.patch.object(prepared_local_tool, "read_workbench_default_aidp_tools", return_value=[row])
    bind_access = mocker.patch.object(prepared_local_tool, "_bind_shared_aidp_access")

    agent = AgentConfig(
        agent_id=8, version_no=3, name="root", model_name="test-model", description="", tools=[tool], origin=origin,
    )
    can_use_platform = platform_allowed and origin == "SYSTEM"

    def export_resource():
        return evaluation_snapshot._export_resource(
            agent, {}, actor.tenant_id, "en", lambda _tenant: [], {},
            allow_workbench_default_aidp=platform_allowed,
        )

    if tenant_binding or can_use_platform:
        exported = export_resource()
        assert exported.tools == [binding]
        result = prepared_local_tool.materialize_local_tools(
            exported, actor, "en", allow_workbench_default_aidp=platform_allowed,
        )
        if tenant_binding:
            export_platform.assert_not_called()
            platform.assert_not_called()
        else:
            export_platform.assert_called_once_with(8, 3)
            platform.assert_called_once_with(8, 3)
        bind_access.assert_called_once_with(result["aidp_search"], actor)
        exported.tools[0].parameters["instance_id"] = 20
        with pytest.raises(HTTPException) as error:
            prepared_local_tool.materialize_local_tools(
                exported, actor, "en", allow_workbench_default_aidp=platform_allowed,
            )
        assert error.value.status_code == 404
        assert bind_access.call_count == 1
    else:
        with pytest.raises(ValueError, match="does not have one enabled instance"):
            export_resource()
        export_platform.assert_not_called()
        with pytest.raises(HTTPException) as error:
            prepared_local_tool.materialize_local_tools(
                resource, actor, "en", allow_workbench_default_aidp=platform_allowed,
            )
        assert error.value.status_code == 404
        platform.assert_not_called()
        bind_access.assert_not_called()
    catalog.assert_called_once_with(8, 3, actor.tenant_id, ["aidp_search"])


@pytest.mark.parametrize("method", [
    "vector_search|full_text_search|graph_search", "graph_search|vector_search",
])
@pytest.mark.parametrize("platform_binding", [False, True])
def test_scoped_shared_aidp_exports_migrated_parameters(mocker, method, platform_binding):
    from infrastructure.local_tool_execution import build_local_tool
    from infrastructure.shared_aidp_tool import SCOPED_SHARED_AIDP_CATALOG_ID
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    mocker.patch.object(environment, "JWT_SECRET", "fixture-signing-key")
    migrated = {
        "search_method": method,
        "vector_candidates": 10, "full_text_candidates": 10, "hybrid_top_k": 0, "graph_top_k": 0,
        "vector_score_threshold": 0.0, "full_text_score_threshold": 0.0, "graph_score_threshold": 0.0,
        "graph_reranking_enable": True, "query_expansion_enable": False, "kwargs": None,
    }
    row = {
        "tool_id": 7, "name": "aidp_search", "class_name": "AidpSearchTool", "source": "local",
        "description": "AIDP search", "inputs": None, "usage": None, "output_type": "string",
        "params": [{"name": key, "default": value} for key, value in migrated.items()],
        "instance_params": {},
    }
    tool = build_local_tool(row, "en", None, None)
    tool.params["kds_list"] = ["authorized"]
    tool.metadata = {SCOPED_SHARED_AIDP_CATALOG_ID: row["tool_id"]}
    for module in (local_tool, prepared_local_tool):
        mocker.patch.object(module, "read_shared_aidp_catalog_tool", return_value=None if platform_binding else row)
    export_platform = mocker.patch.object(local_tool, "read_workbench_scoped_aidp_tool", return_value=row)
    restore_platform = mocker.patch.object(prepared_local_tool, "read_workbench_scoped_aidp_tool", return_value=row)
    binding = local_tool.export_scoped_shared_aidp(
        tool, 8, 3, "tenant-a", "en", allow_workbench_default_aidp=platform_binding,
    )
    expected = {key: value for key, value in migrated.items() if key != "kwargs"}
    assert binding.parameters["options"] == {**expected, "kds_list": ["authorized"]}
    resource = SimpleNamespace(agent_id=8, version_no=3, origin="SYSTEM", tools=[binding])
    actor = ServicePrincipal("user-a", "tenant-a")
    bind_access = mocker.patch.object(prepared_local_tool, "_bind_shared_aidp_access")
    rebound = prepared_local_tool.materialize_local_tools(
        resource, actor, "en", allow_scoped_aidp=True, allow_workbench_default_aidp=platform_binding,
    )
    assert rebound["aidp_search"].params == binding.parameters["options"]
    bind_access.assert_called_once_with(rebound["aidp_search"], actor)
    for lookup in (export_platform, restore_platform):
        if platform_binding:
            lookup.assert_called_once_with(7, 8, 3)
        else:
            lookup.assert_not_called()


@pytest.mark.parametrize("invalid", [
    {"search_method": "vector_search|unknown"},
    {"vector_candidates": 0},
    {"full_text_candidates": 501},
    {"hybrid_top_k": 101},
    {"graph_top_k": -1},
    {"vector_score_threshold": 1.1},
    {"graph_reranking_enable": 1},
    {"kwargs": {"server_url": "unexpected"}},
    {"api_key": "unexpected"},
])
def test_scoped_shared_aidp_rejects_invalid_retrieval_options(invalid):
    from pydantic import ValidationError

    from contracts.agentos import ScopedSharedAidpOptions

    with pytest.raises(ValidationError):
        ScopedSharedAidpOptions.model_validate({"kds_list": [], **invalid})


@pytest.mark.asyncio
async def test_scoped_aidp_accepts_catalog_localization_only(mocker):
    from contextlib import nullcontext

    from management.db.tool import repository
    from management.services.agent.preparation import local_tool, tools

    mocker.patch.object(environment, "JWT_SECRET", "fixture-signing-key")
    row = {
        "tool_id": 7, "name": "aidp_search", "class_name": "AidpSearchTool", "source": "local",
        "description": "AIDP search", "usage": None, "output_type": "string",
        "inputs": '{"query":{"type":"string"}}', "params": [{"name": "top_k", "default": 10}],
        "instance_params": {},
    }
    session = mocker.Mock()
    session.query.return_value.filter.return_value.first.return_value = SimpleNamespace(params=row["params"])
    mocker.patch.object(repository, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(repository, "as_dict", return_value=dict(row))
    decorated = repository.add_tool_field({"tool_id": 7, "params": {}})
    assert decorated["description_zh"]
    assert decorated["inputs"] != '{"query":{"type":"string"}}'
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={})
    tool, = await tools.create_tool_config_list(
        8, "tenant-a", "user-a", language="zh", version_no=3,
        runtime_knowledge_tools=[decorated], portable_evaluation=True,
    )
    mocker.patch.object(local_tool, "read_shared_aidp_catalog_tool", return_value=row)
    binding = local_tool.export_scoped_shared_aidp(tool, 8, 3, "tenant-a", "zh")
    assert binding.parameters["options"] == {"top_k": 10, "kds_list": []}
    assert binding.parameters["catalog_tool_id"] == 7
    assert "description_zh" not in binding.parameters
    for change in ({"description_zh": "tampered"}, {"inputs": "{}"}, {"usage": "tampered"}):
        with pytest.raises(ValueError, match="differs from its catalog"):
            local_tool.export_scoped_shared_aidp(tool.model_copy(update=change), 8, 3, "tenant-a", "zh")


@pytest.mark.parametrize("mode", ["invalid-id", "nonempty-kwargs", "no-sdk-description"])
def test_scoped_aidp_rejects_untrusted_catalog_options(mocker, mode):
    from pydantic import ValidationError

    from infrastructure.local_tool_execution import build_local_tool
    from infrastructure.shared_aidp_tool import SCOPED_SHARED_AIDP_CATALOG_ID
    from management.services.agent.preparation import local_tool

    row = {
        "tool_id": 7, "name": "aidp_search", "class_name": "AidpSearchTool", "source": "local",
        "description": "AIDP search", "inputs": None, "usage": None, "output_type": "string",
        "params": [], "instance_params": {},
    }
    tool = build_local_tool(row, "en", None, None)
    tool.metadata = {SCOPED_SHARED_AIDP_CATALOG_ID: 7}
    tenant_lookup = mocker.patch.object(local_tool, "read_shared_aidp_catalog_tool", return_value=row)
    platform_lookup = mocker.patch.object(local_tool, "read_workbench_scoped_aidp_tool")
    localized_catalog = mocker.patch.object(local_tool, "get_local_tools_description_zh", return_value={})

    if mode == "invalid-id":
        tool.metadata[SCOPED_SHARED_AIDP_CATALOG_ID] = True
        with pytest.raises(ValueError, match="requires an available tenant catalog tool"):
            local_tool.export_scoped_shared_aidp(tool, 8, 3, "tenant-a", "en", allow_workbench_default_aidp=True)
        tenant_lookup.assert_not_called()
        localized_catalog.assert_not_called()
    elif mode == "nonempty-kwargs":
        tool.params["kwargs"] = {"unexpected": True}
        with pytest.raises(ValidationError) as error:
            local_tool.export_scoped_shared_aidp(tool, 8, 3, "tenant-a", "en")
        assert error.value.errors()[0]["loc"] == ("kwargs",)
        assert error.value.errors()[0]["type"] == "extra_forbidden"
        localized_catalog.assert_not_called()
    else:
        tool.description_zh = "Unexpected description"
        with pytest.raises(ValueError, match="differs from its catalog"):
            local_tool.export_scoped_shared_aidp(tool, 8, 3, "tenant-a", "en")
        localized_catalog.assert_called_once_with()
    platform_lookup.assert_not_called()
