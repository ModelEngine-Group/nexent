# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from contracts.agentos import PreparedEvaluationRun
from fastapi import HTTPException
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from test.common.local_agent_tools import create_local_tool
from runtime.agentos import prepared_evaluation

from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from test.backend.app.test_agentos_prepared_evaluation import (
    model_record,
)




@pytest.fixture(autouse=True)
def metadata_client(mocker):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from contracts.agentos import ModelMetadata
    from management.services.agent.preparation import knowledge_search

    client = SimpleNamespace(get_model=AsyncMock(return_value=ModelMetadata(
        model_id=12, model_type="embedding", display_name="Embedding", revision="revision-1")), list_models=AsyncMock())
    mocker.patch.object(knowledge_search, "AgentOSClient", return_value=client)
    async def blocking(name, method, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return method(*args, **kwargs)
    mocker.patch.object(knowledge_search, "run_blocking", side_effect=blocking)
    return client


@pytest.fixture
def knowledge_tool(mocker):
    from contracts.agentos_knowledge import KnowledgeFileReference
    mocker.patch("management.services.agent.preparation.knowledge_search.prepare_tool_files", return_value=[
        KnowledgeFileReference(knowledge_id=7, file_id="a" * 32, file_version=0)])
    return ToolConfig(
        name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local", usage="knowledge",
        params={"index_names": ["kb-authorized", "kb-denied"], "search_mode": "accurate", "top_k": 4},
    )


@pytest.mark.parametrize("shared", [False, True])
def test_materialized_tool_keeps_live_resource_namespace(mocker, shared):
    from types import SimpleNamespace

    from contracts.agentos import KnowledgeSearchBinding
    from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from runtime.agentos import prepared_knowledge

    actor = ServicePrincipal("user-a", "tenant-a")
    resource = KnowledgeBaseGrant(
        knowledge_id=7, collection="kb-authorized", embedding_model_id=12,
        resource_tenant_id=ASSET_OWNER_TENANT_ID if shared else actor.tenant_id,
        revision="a" * 64,
    )
    binding = KnowledgeSearchBinding(
        description={}, index_names=[resource.collection],
        allowed=[{"knowledge_id": 7, "index_name": resource.collection, "revision": resource.revision}],
        display_name_to_index={}, embedding_models={resource.collection: {"model_id": 12, "revision": "r1"}},
    )
    mocker.patch.object(prepared_knowledge, "default_service", return_value=SimpleNamespace(client=object(), models=object()))
    mocker.patch.object(prepared_knowledge, "_current_grant", return_value=KnowledgeSearchGrant(knowledge_bases=[resource]))
    load = mocker.patch.object(prepared_knowledge, "_load_model")
    tool = prepared_knowledge._materialize_knowledge_search_tool(binding, actor, "knowledge_base_search")
    search = tool.metadata["knowledge_searcher"].search
    actual, model = search.bindings[resource.collection]
    assert actual == resource and actual is not resource
    assert search.actor == actor and model.model_id == 12
    load.assert_called_once_with(binding.embedding_models[resource.collection], actor.tenant_id, {"embedding", "multi_embedding"})


@pytest.mark.parametrize(("change", "status"), [
    ("none", None), ("deny_all", None), ("revoked", 403), ("stale", 409), ("stale_model", 409), ("foreign", 404),
])
@pytest.mark.parametrize("aliased", [False, True])
@pytest.mark.asyncio
async def test_prepared_knowledge_search_preserves_scope_and_model_revision(mocker, knowledge_tool, change, status, aliased, metadata_client):
    from management.services.agent.preparation import knowledge_search
    from runtime.agentos import prepared_knowledge

    if aliased:
        knowledge_tool.name = "tenant_knowledge"
    index = {
        "knowledge_id": 7, "index_name": "kb-authorized", "tenant_id": "tenant-a", "knowledge_name": "Authorized",
        "created_by": "user-a", "embedding_model_id": 12,
    }
    denied = {
        "knowledge_id": 8, "index_name": "kb-denied", "tenant_id": "tenant-a", "knowledge_name": "Denied",
        "created_by": "other", "embedding_model_id": 13,
    }
    embedding = model_record(model_id=12, model_type="embedding", api_key="private-embedding-credential")
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[index, denied])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={
        "kb-authorized": None if change == "deny_all" else "READ_ONLY", "kb-denied": None,
    })
    model_lookup = metadata_client.get_model
    await knowledge_search.prepare_knowledge_search(knowledge_tool, "user-a", "tenant-a", ["reports/approved.txt"])

    llm = model_record(model_id=11)
    mocker.patch("management.services.agent.preparation.model_bindings.get_model_by_model_id", return_value=llm)
    mocker.patch("management.services.agent.preparation.model_bindings.read_agent_model_overrides", return_value={})
    mocker.patch("runtime.model.parameters.read_agent_model_overrides", return_value={})
    selected = create_model_config_from_record(llm)
    agent = AgentConfig(
        agent_id=7, version_no=2, name="evaluation", description="", model_name=selected.cite_name,
        tools=[knowledge_tool],
    )
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[llm])
    stub_resolved_model_catalog(mocker, llm)
    snapshot = evaluation_snapshot.export_snapshot(
        agent, [selected], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    )
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    assert "private-embedding-credential" not in encoded
    if change == "deny_all":
        model_lookup.assert_not_called()
    else:
        model_lookup.assert_called_once_with(12, "user-a", "tenant-a")

    runtime_records = [] if change == "foreign" else [dict(index, embedding_model_id=13) if change == "stale" else index]
    from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant
    from contracts.errors.exceptions import RuntimeUpstreamError

    from infrastructure.knowledge_search import knowledge_search_revision
    def current_grant(binding, actor, client):
        if change in {"revoked", "foreign"}:
            raise RuntimeUpstreamError(status_code=403 if change == "revoked" else 404,
                                       content=b'{"code":"DENIED"}', headers={})
        return KnowledgeSearchGrant(knowledge_bases=[KnowledgeBaseGrant(
            resource_tenant_id=row["tenant_id"], knowledge_id=row["knowledge_id"], collection=row["index_name"], embedding_model_id=row["embedding_model_id"],
            revision=knowledge_search_revision(row)) for row in runtime_records])
    mocker.patch.object(prepared_knowledge, "_current_grant", side_effect=current_grant)
    if change == "revoked":
        runtime_records[0] = dict(index, created_by="other", group_ids="99", ingroup_permission="PRIVATE")
    mocker.patch.object(prepared_knowledge, "get_model_by_model_id", return_value=(
        embedding | {"update_time": "revision-2"} if change == "stale_model" else embedding
    ))
    build_adapter = mocker.patch.object(prepared_knowledge, "build_adapter_fresh")
    vector = mocker.patch("infrastructure.vdb.client.create_elasticsearch_core")
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=llm)

    payload = PreparedEvaluationRun.model_validate_json(encoded)
    actor = ServicePrincipal("user-b", "tenant-b") if change == "foreign" else ServicePrincipal("user-a", "tenant-a")
    if status:
        with pytest.raises(HTTPException) as error:
            prepared_evaluation.prepare_evaluation_run(payload, actor)
        assert error.value.status_code == status
        build_adapter.assert_not_called()
        vector.assert_not_called()
    else:
        info = prepared_evaluation.prepare_evaluation_run(payload, actor)
        assert info.agent_config.tools[0].name == knowledge_tool.name
        tool = create_local_tool(info.agent_config.tools[0])
        assert tool.name == "knowledge_base_search"
        assert not hasattr(tool, "_internal_document_paths")
        denied_scope = tool._resolve_search_scope(["Denied"])
        assert denied_scope.permission_denied_scope == ["kb-denied"]
        assert "kb-denied" not in denied_scope.used_scope
        if change == "deny_all":
            assert tool._resolve_search_scope(None).used_scope == []
            build_adapter.assert_not_called()
            vector.assert_not_called()
        else:
            assert tool._resolve_search_scope(["Authorized"]).used_scope == ["kb-authorized"]
            assert not hasattr(tool, "embedding_model")
            assert callable(tool.searcher)
            build_adapter.assert_not_called()
            assert not hasattr(tool, "vdb_core")
            vector.assert_not_called()





@pytest.mark.parametrize("named_available", [True, False])
@pytest.mark.asyncio
async def test_prepared_knowledge_reranking_keeps_named_then_tenant_default(mocker, knowledge_tool, named_available, metadata_client):
    from contracts.agentos import ToolBinding
    from management.services.agent.preparation import knowledge_search
    from runtime.agentos import prepared_knowledge

    knowledge_tool.params.update(rerank=True, rerank_model_name="repo/named")
    index = {
        "knowledge_id": 7, "index_name": "kb-authorized", "tenant_id": "tenant-a",
        "knowledge_name": "Authorized", "created_by": "user-a", "embedding_model_id": 12,
    }
    embedding = model_record(model_id=12, model_type="multi_embedding")
    named = model_record(model_id=13, model_type="rerank", api_key="private-named-reranker")
    default = model_record(model_id=14, model_type="rerank", api_key="private-default-reranker")
    records = {row["model_id"]: row for row in (embedding, named, default)}

    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[index])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={"kb-authorized": "EDIT"})
    from contracts.agentos import ModelCatalogEntry, ModelCatalogPage, ModelMetadata
    def metadata(record):
        return ModelMetadata(model_id=record["model_id"], model_type=record["model_type"],
                             display_name=record["display_name"], revision="revision-1")
    metadata_client.get_model.side_effect = lambda model_id, user, tenant: metadata(records[model_id])
    metadata_client.list_models.return_value = ModelCatalogPage(models=[ModelCatalogEntry(
        **metadata(named).model_dump(exclude={"qualified_name"}), qualified_name="repo/named")] if named_available else [])
    mocker.patch.object(knowledge_search.tenant_config_manager, "get_app_config", return_value="14")
    assert await knowledge_search.prepare_knowledge_search(knowledge_tool, "user-a", "tenant-a", None)
    binding = ToolBinding(tool_id=knowledge_tool.name, version="2", parameters=knowledge_tool.metadata["prepared_knowledge_search"])
    assert "private-named-reranker" not in binding.model_dump_json()
    assert "private-default-reranker" not in binding.model_dump_json()

    from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant

    from infrastructure.knowledge_search import knowledge_search_revision
    mocker.patch.object(prepared_knowledge, "_current_grant", return_value=KnowledgeSearchGrant(knowledge_bases=[
        KnowledgeBaseGrant(knowledge_id=7, collection="kb-authorized", resource_tenant_id=index["tenant_id"], embedding_model_id=12,
                           revision=knowledge_search_revision(index))]))
    lookup = mocker.patch.object(prepared_knowledge, "get_model_by_model_id",
                                side_effect=lambda model_id, tenant: records[model_id])
    mocker.patch("infrastructure.vdb.client.create_elasticsearch_core")
    adapter = mocker.patch.object(prepared_knowledge, "build_adapter_fresh", side_effect=[
        "embedding", "named" if named_available else ValueError("not configured"), "default",
    ])
    tools = prepared_knowledge.materialize_knowledge_search([binding], ServicePrincipal("user-a", "tenant-a"))
    assert tools[knowledge_tool.name].metadata["knowledge_searcher"].rerank_model.model_id == (13 if named_available else 14)
    adapter.assert_not_called()
    assert [call.args for call in lookup.call_args_list] == [(12, "tenant-a"), (13 if named_available else 14, "tenant-a")]




@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "override", "disabled", "native"])
async def test_portable_tool_compiler_resolves_knowledge_without_building_legacy_clients(mocker, mode, knowledge_tool):
    from types import SimpleNamespace

    from contracts.agent import AgentRequest, WorkbenchSessionConfig
    from contracts.tool import ToolParamsRequest
    from management.services.agent import workbench
    from management.services.agent.preparation import knowledge_search, tools
    from management.services.knowledge_base import mount, scope

    definition = {
        "class_name": "KnowledgeBaseSearchTool", "name": "knowledge_base_search", "source": "local",
        "params": [{"name": "index_names", "default": ["kb-one"]},
                   {"name": "top_k", "default": 3, "type": "integer"}],
        "is_available": True,
    }
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[definition] if mode in (None, "native") else [])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    legacy_vector = mocker.patch.object(tools, "get_vector_db_core")
    legacy_embedding = mocker.patch.object(tools, "get_embedding_model_by_index_name")
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[{
        "knowledge_id": 7, "index_name": "kb-one", "knowledge_name": "One", "tenant_id": "tenant-a",
        "created_by": "user-a", "embedding_model_id": 12,
    }])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={"kb-one": "EDIT"})

    tool_overrides = {"document_paths": ["report.txt"]}
    if mode == "override":
        tool_overrides["top_k"] = 5
    tool_params = ToolParamsRequest.model_validate({
        "agents": {"root": {"tools": {"knowledge_base_search": {"document_paths": ["report.txt"], **({"top_k": 5} if mode == "override" else {})}}}},
    })
    compiler_options = {}
    if mode == "native":
        mocker.patch.object(scope, "resolve_root_version", return_value=2)
        mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
            {"agent_id": 7, "version_no": 2, "agent_name": "root", "tools": [definition]},
            {"agent_id": 8, "version_no": 3, "agent_name": "child", "tools": [definition]},
        ])
        mocker.patch.object(scope, "get_knowledge_info_by_ids_and_tenant", return_value=[
            {"knowledge_id": 7, "index_name": "kb-one", "knowledge_name": "One", "embedding_model_id": 12},
        ])
        mocker.patch.object(scope.ElasticSearchService, "filter_accessible_indices", return_value=["kb-one"])
        native = evaluation_snapshot.prepare_native_knowledge(AgentRequest(
            query="query", agent_id=7, tool_params=tool_params, knowledge_scope={
                "local": {"mode": "override", "knowledge_ids": ["7"]}, "aidp": {"mode": "disabled"},
            },
        ), {}, "user-a", "tenant-a")
        assert native.authorized_tools[(8, 3)] == {"knowledge_base_search": {"index_names": ["kb-one"]}}
        compiler_options["authorized_knowledge_tools"] = native.authorized_tools
        tool_params = native.resolution.tool_params
    elif mode is not None:
        config = WorkbenchSessionConfig(
            mode="generic_chat",
            knowledge_scope={
                "local": {"mode": mode, "knowledge_ids": ["7", "8"] if mode == "override" else []},
                "aidp": {"mode": "disabled"},
            },
        )
        root = SimpleNamespace(agent_id=7, version_no=2)
        plan = SimpleNamespace(root=SimpleNamespace(identity=root), root_skills=())
        mocker.patch.object(mount, "ENABLE_AIDP_KNOWLEDGE", False)
        mocker.patch.object(workbench, "resolve_workbench_config", return_value=(config, plan))
        mocker.patch.object(mount, "query_all_tools", return_value=[definition])
        mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
            {"agent_name": "root", "tools": []}, {"agent_name": "child", "tools": [definition]},
        ])
        records = mocker.patch.object(scope, "get_knowledge_info_by_ids_and_tenant", return_value=[
            {"knowledge_id": 7, "index_name": "kb-one", "knowledge_name": "One", "embedding_model_id": 12},
            {"knowledge_id": 8, "index_name": "kb-denied", "knowledge_name": "Denied", "embedding_model_id": 12},
        ])
        permissions = mocker.patch.object(scope.ElasticSearchService, "filter_accessible_indices", return_value=["kb-one"])
        request = AgentRequest(query="query", entrypoint="workbench", workbench=config, tool_params=tool_params)
        plan = workbench.prepare_portable_workbench(request, None, "user-a", "tenant-a")
        compiler_options["runtime_knowledge_tools"] = plan.knowledge_tools
        tool_params = plan.knowledge.tool_params
        assert "child" not in tool_params.agents
        if mode == "override":
            records.assert_called_once_with([7, 8], "tenant-a")
            permissions.assert_called_once_with(["kb-one", "kb-denied"], user_id="user-a", tenant_id="tenant-a")
            assert plan.knowledge.local_knowledge_ids == ["7"]
            assert plan.knowledge.warnings == [{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE", "source": "local", "count": 1}]
        else:
            records.assert_not_called()
            assert plan.knowledge.local_disabled

    compiled = await tools.create_tool_config_list(
        7, "tenant-a", "user-a", version_no=2, portable_evaluation=True,
        tool_params=tool_params, **compiler_options,
    )
    legacy_vector.assert_not_called()
    legacy_embedding.assert_not_called()
    if mode == "disabled":
        assert compiled == []
        return

    result, = compiled
    descriptor = result.metadata["prepared_knowledge_search"]
    assert descriptor["top_k"] == (5 if mode == "override" else 3)
    assert descriptor["index_names"] == ["kb-one"]
    assert descriptor["file_refs"] == [{"knowledge_id": 7, "file_id": "a" * 32, "file_version": 0}]
    assert descriptor["embedding_models"] == {"kb-one": {"model_id": 12, "revision": "revision-1"}}
    assert result.metadata["allowed_index_names"] == ["kb-one"]
    assert result.metadata["index_name_to_display_map"] == {"kb-one": "One"}


def test_prepared_model_revision_matches_database_list_and_id_formats(mocker):
    from datetime import datetime


    row = model_record(model_id=11, update_time=datetime(2026, 11, 10, 13, 40))
    selected = create_model_config_from_record(row)
    mocker.patch("management.services.agent.preparation.model_bindings.get_model_by_model_id", return_value=row)
    mocker.patch("management.services.agent.preparation.model_bindings.read_agent_model_overrides", return_value={})
    mocker.patch("runtime.model.parameters.read_agent_model_overrides", return_value={})
    listed = row | {"update_time": "2026-11-10T13:40:00Z"}
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[listed])
    stub_resolved_model_catalog(mocker, listed)
    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=row)
    agent = AgentConfig(agent_id=7, version_no=2, name="agent", description="", model_name=selected.cite_name, tools=[])
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    prepared = evaluation_snapshot.export_snapshot(agent, [selected], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")

    assert prepared.models.llm.revision == listed["update_time"]
    actor = ServicePrincipal("user-a", "tenant-a")
    assert prepared_evaluation.prepare_evaluation_run(prepared, actor).model_config_list[0] == selected
    prepared.models.llm.revision = "2026-11-10T13:40:00"
    assert prepared_evaluation.prepare_evaluation_run(prepared, actor).model_config_list[0] == selected


@pytest.mark.parametrize("binding_ids", [["sdk_knowledge:"], ["sdk_knowledge:tenant", "sdk_knowledge:tenant"]])
def test_knowledge_alias_shape_is_rejected_before_storage_access(mocker, binding_ids):
    from contracts.agentos import ToolBinding
    from runtime.agentos import prepared_knowledge

    lookup = mocker.patch.object(prepared_knowledge, "_current_grant")
    if len(binding_ids) == 1:
        params = {}
    else:
        params = {"description": {}, "index_names": [], "allowed": [], "display_name_to_index": {}}
    with pytest.raises(ValueError):
        prepared_knowledge.materialize_knowledge_search(
            [ToolBinding(tool_id=value, version="1", parameters=params) for value in binding_ids],
            ServicePrincipal("user-a", "tenant-a"),
        )
    lookup.assert_not_called()


def test_distinct_knowledge_catalog_aliases_keep_independent_sdk_configuration(mocker):
    from types import SimpleNamespace

    from contracts.agentos import ToolBinding
    from runtime.agentos import prepared_knowledge

    storage = mocker.patch.object(prepared_knowledge, "_current_grant")
    models = mocker.patch.object(prepared_knowledge, "get_model_by_model_id")
    vector = mocker.patch("infrastructure.vdb.client.create_elasticsearch_core")
    references = [ToolBinding(tool_id="sdk_knowledge:" + name, version="2", parameters={
        "description": {}, "index_names": [], "allowed": [], "display_name_to_index": {}, "top_k": top_k,
    }) for name, top_k in [("first", 3), ("second", 7)]]
    actual = prepared_knowledge.materialize_knowledge_search(references, ServicePrincipal("user-a", "tenant-a"))
    assert list(actual) == [item.tool_id for item in references]
    assert [(tool.name, tool.params["top_k"]) for tool in actual.values()] == [("first", 3), ("second", 7)]
    for config in actual.values():
        sdk = create_local_tool(config)
        assert sdk.name == "knowledge_base_search"
        assert sdk._resolve_search_scope(None).used_scope == []
        assert callable(config.metadata["image_filterer"])
        assert sdk.image_filterer is config.metadata["image_filterer"]
        assert sdk.image_filterer.actor == ServicePrincipal("user-a", "tenant-a")
    storage.assert_not_called()
    models.assert_not_called()
    vector.assert_not_called()

from test.backend.services.model_profile_helpers import stub_resolved_model_catalog
