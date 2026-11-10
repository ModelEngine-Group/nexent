# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from fastapi import HTTPException

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from runtime.agentos import prepared_evaluation

from test.backend.app.test_agentos_prepared_evaluation import model_record


@pytest.fixture
def knowledge_tool():
    return ToolConfig(
        name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local", usage="knowledge",
        params={"index_names": ["kb-authorized", "kb-denied"], "search_mode": "accurate", "top_k": 4},
    )


@pytest.mark.parametrize(("change", "status"), [
    ("none", None), ("deny_all", None), ("revoked", 403), ("stale", 409), ("stale_model", 409), ("foreign", 404),
])
def test_prepared_knowledge_search_preserves_scope_and_model_revision(mocker, knowledge_tool, change, status):
    from management.services.agent.preparation import knowledge_search
    from runtime.agentos import prepared_knowledge

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
    model_lookup = mocker.patch.object(knowledge_search, "get_model_by_model_id", return_value=embedding)
    knowledge_search.prepare_knowledge_search(knowledge_tool, "user-a", "tenant-a", ["reports/approved.txt"])

    llm = model_record(model_id=11)
    selected = create_model_config_from_record(llm)
    agent = AgentConfig(
        agent_id=7, version_no=2, name="evaluation", description="", model_name=selected.cite_name,
        tools=[knowledge_tool],
    )
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[llm])
    snapshot = evaluation_snapshot.export_snapshot(
        agent, [selected], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    )
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    assert "private-embedding-credential" not in encoded
    if change == "deny_all":
        model_lookup.assert_not_called()
    else:
        model_lookup.assert_called_once_with(12, "tenant-a")

    runtime_records = [] if change == "foreign" else [dict(index, embedding_model_id=13) if change == "stale" else index]
    mocker.patch.object(prepared_knowledge, "read_knowledge_search_records", return_value=runtime_records)
    mocker.patch.object(prepared_knowledge, "read_knowledge_search_actor", return_value=(
        {"tenant_id": "tenant-a", "user_role": "USER"}, [],
    ))
    if change == "revoked":
        runtime_records[0] = dict(index, created_by="other", group_ids="99", ingroup_permission="PRIVATE")
    mocker.patch.object(prepared_knowledge, "get_model_by_model_id", return_value=(
        embedding | {"update_time": "revision-2"} if change == "stale_model" else embedding
    ))
    build_adapter = mocker.patch.object(prepared_knowledge, "build_adapter_fresh")
    vector = mocker.patch.object(prepared_knowledge, "create_elasticsearch_core")
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
        tool = NexentAgent.create_local_tool(info, info.agent_config.tools[0])
        assert tool._internal_document_paths == ["reports/approved.txt"]
        denied_scope = tool._resolve_search_scope(["Denied"])
        assert denied_scope.permission_denied_scope == ["kb-denied"]
        assert "kb-denied" not in denied_scope.used_scope
        if change == "deny_all":
            assert tool._resolve_search_scope(None).used_scope == []
            build_adapter.assert_not_called()
            vector.assert_not_called()
        else:
            assert tool._resolve_search_scope(["Authorized"]).used_scope == ["kb-authorized"]
            assert tool.embedding_model is build_adapter.return_value
            assert tool.vdb_core is vector.return_value
            assert tool._filter_by_document_paths([
                {"path_or_url": "reports/other.txt"}, {"path_or_url": "reports/approved.txt"},
            ]) == [{"path_or_url": "reports/approved.txt"}]




@pytest.mark.parametrize("named_available", [True, False])
def test_prepared_knowledge_reranking_keeps_named_then_tenant_default(mocker, knowledge_tool, named_available):
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
    mocker.patch.object(knowledge_search, "get_model_by_model_id", return_value=embedding)
    mocker.patch.object(knowledge_search, "find_named_rerank_record", return_value=named)
    mocker.patch.object(knowledge_search.tenant_config_manager, "get_model_config", return_value=default)
    assert knowledge_search.prepare_knowledge_search(knowledge_tool, "user-a", "tenant-a", None)
    binding = ToolBinding(tool_id=knowledge_tool.name, version="1", parameters=knowledge_tool.metadata["prepared_knowledge_search"])
    assert "private-named-reranker" not in binding.model_dump_json()
    assert "private-default-reranker" not in binding.model_dump_json()

    mocker.patch.object(prepared_knowledge, "read_knowledge_search_records", return_value=[index])
    mocker.patch.object(prepared_knowledge, "read_knowledge_search_actor", return_value=(
        {"tenant_id": "tenant-a", "user_role": "USER"}, [],
    ))
    lookup = mocker.patch.object(prepared_knowledge, "get_model_by_model_id",
                                side_effect=lambda model_id, tenant: records[model_id])
    mocker.patch.object(prepared_knowledge, "create_elasticsearch_core")
    adapter = mocker.patch.object(prepared_knowledge, "build_adapter_fresh", side_effect=[
        "embedding", "named" if named_available else ValueError("not configured"), "default",
    ])
    tools = prepared_knowledge.materialize_knowledge_search([binding], ServicePrincipal("user-a", "tenant-a"))
    assert tools[knowledge_tool.name].metadata["rerank_model"] == ("named" if named_available else "default")
    assert adapter.call_args_list[0].args[1:3] == ("multi_embedding", "multiEmbedding")
    assert [call.args for call in lookup.call_args_list] == (
        [(12, "tenant-a"), (13, "tenant-a")] + ([] if named_available else [(14, "tenant-a")])
    )



@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "override", "disabled"])
async def test_portable_tool_compiler_resolves_knowledge_without_building_legacy_clients(mocker, mode):
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
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[definition] if mode is None else [])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    legacy_vector = mocker.patch.object(tools, "get_vector_db_core")
    legacy_embedding = mocker.patch.object(tools, "get_embedding_model_by_index_name")
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[{
        "knowledge_id": 7, "index_name": "kb-one", "knowledge_name": "One", "tenant_id": "tenant-a",
        "created_by": "user-a", "embedding_model_id": 12,
    }])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={"kb-one": "EDIT"})
    mocker.patch.object(knowledge_search, "get_model_by_model_id", return_value=model_record(
        model_id=12, model_type="embedding",
    ))

    tool_params = ToolParamsRequest.model_validate({
        "agents": {"root": {"tools": {"knowledge_base_search": {"document_paths": ["report.txt"]}}}},
    })
    compiler_options = {}
    if mode is not None:
        config = WorkbenchSessionConfig(
            mode="generic_chat",
            knowledge_scope={
                "local": {"mode": mode, "knowledge_ids": ["7", "8"] if mode == "override" else []},
                "aidp": {"mode": "disabled"},
                "retrieval_config": {"top_k": 5},
            },
        )
        root = SimpleNamespace(agent_id=7, version_no=2)
        plan = SimpleNamespace(root=SimpleNamespace(identity=root), root_skills=())
        mocker.patch.object(workbench, "ENABLE_AIDP_KNOWLEDGE", False)
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
    assert descriptor["document_paths"] == ["report.txt"]
    assert descriptor["embedding"] == {"model_id": 12, "revision": "revision-1"}
    assert result.metadata["allowed_index_names"] == ["kb-one"]
    assert result.metadata["index_name_to_display_map"] == {"kb-one": "One"}


def test_prepared_model_revision_matches_database_list_and_id_formats(mocker):
    from datetime import datetime


    row = model_record(model_id=11, update_time=datetime(2026, 11, 10, 13, 40))
    selected = create_model_config_from_record(row)
    listed = row | {"update_time": "2026-11-10T13:40:00Z"}
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[listed])
    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=row)
    agent = AgentConfig(agent_id=7, version_no=2, name="agent", description="", model_name=selected.cite_name, tools=[])
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    prepared = evaluation_snapshot.export_snapshot(agent, [selected], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")

    assert prepared.models.llm.revision == listed["update_time"]
    actor = ServicePrincipal("user-a", "tenant-a")
    assert prepared_evaluation.prepare_evaluation_run(prepared, actor).model_config_list[0] == selected
    prepared.models.llm.revision = "2026-11-10T13:40:00"
    assert prepared_evaluation.prepare_evaluation_run(prepared, actor).model_config_list[0] == selected
