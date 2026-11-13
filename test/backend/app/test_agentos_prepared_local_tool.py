# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import ToolBinding
from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent


@pytest.fixture
def stored_tool(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-local-tool-secret")
    return {
        "tool_instance_id": 24, "tool_id": 10, "name": "dify_search", "class_name": "DifySearchTool",
        "source": "local", "description": "Search", "usage": None, "inputs": None, "output_type": "string",
        "params": [{"name": name, "default": value} for name, value in {
            "server_url": "https://private-dify.invalid/v1", "api_key": "local-only-dify-key",
            "dataset_ids": '["dataset-a"]', "top_k": 4, "rerank": True, "rerank_model_name": "Reranker",
        }.items()],
        "instance_params": {"top_k": 2, "dataset_ids": None},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [None, {"top_k": 7}, {"top_k": True}, {"top_k": 101}, {"api_key": "request-key"},
    {"rerank": False}, {"rerank": True, "rerank_model_name": "Alternate"}, {"rerank_model_name": ""}])
async def test_local_tool_compiles_and_rebinds_without_sending_connection_fields(mocker, stored_tool, requested):
    from management.services.agent.preparation import local_tool, tools
    from runtime.agentos import prepared_local_tool

    params = [{**item, "default": 2} if item["name"] == "top_k" else item for item in stored_tool["params"]]
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[
        {**stored_tool, "params": params, "description_zh": "检索"},
    ])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "agent"})
    legacy = mocker.patch.object(tools, "get_rerank_model")
    tool, = await tools.create_tool_config_list(
        7, "tenant-a", "user-a", version_no=3, portable_evaluation=True,
        tool_params={"agents": {"agent": {"tools": {"dify_search": requested}}}} if requested else None,
    )
    legacy.assert_not_called()

    rerank = mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    if requested and requested in ({"top_k": True}, {"top_k": 101}, {"api_key": "request-key"}):
        with pytest.raises(ValueError):
            local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
        rerank.assert_not_called()
        return
    exported = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
    if requested:
        assert exported.parameters["search_overrides"] == requested
    else:
        assert "search_overrides" not in exported.parameters
    rerank_name = tool.params.get("rerank_model_name") if tool.params.get("rerank") else None
    if rerank_name:
        rerank.assert_called_once_with("tenant-a", rerank_name)
    else:
        rerank.assert_not_called()
    encoded = exported.model_dump_json()
    for secret in ("https://private-dify.invalid/v1", "local-only-dify-key", "dataset-a"):
        assert secret not in encoded
    lookup = mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[stored_tool])
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")
    resource = SimpleNamespace(agent_id=7, version_no=3, tools=[ToolBinding.model_validate_json(encoded)])
    rebound = prepared_local_tool.materialize_local_tools(resource, ServicePrincipal("user-a", "tenant-a"), "zh")[tool.name]
    lookup.assert_called_once_with(7, 3, "tenant-a", ["dify_search"])
    assert rebound.description_zh == "检索"
    assert rebound.params == tool.params
    instance = NexentAgent.create_local_tool(SimpleNamespace(observer=None), rebound)
    assert instance.dataset_ids == ["dataset-a"]
    assert instance.top_k == (requested or {}).get("top_k", 2)
    assert instance.rerank_model is (hydrate_rerank.return_value if rerank_name else None)
    if not rerank_name:
        hydrate_rerank.assert_not_called()


@pytest.mark.parametrize(("change", "status"), [("revoked", 404), ("changed", 409), ("covered_default", 409)])
def test_local_tool_refuses_removed_or_changed_binding(mocker, stored_tool, change, status):
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    tool = ToolConfig(
        class_name="DifySearchTool", name="dify_search", description="Search", output_type="string",
        source="local", params={item["name"]: item["default"] for item in stored_tool["params"]} | {"top_k": 2},
    )
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
    if change == "covered_default":
        binding.parameters["search_overrides"] = {"top_k": 7}
    rows = [] if change == "revoked" else [{**stored_tool, "instance_params": {"top_k": 9}}]
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=rows)
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")

    with pytest.raises(HTTPException) as error:
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]),
            ServicePrincipal("user-a", "tenant-a"), "zh",
        )

    assert error.value.status_code == status
    hydrate_rerank.assert_not_called()


@pytest.mark.parametrize("overrides", [{"api_key": "injected"}, {"max_results": 7}])
def test_local_tool_rejects_unsupported_signed_search_overrides(mocker, stored_tool, overrides):
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    tool = build_local_tool(stored_tool, "zh", None, None)
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
    binding.parameters["search_overrides"] = overrides
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[stored_tool])
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")

    with pytest.raises(ValueError):
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "zh",
        )
    hydrate_rerank.assert_not_called()


@pytest.mark.parametrize(("name", "values", "accepted"), [
    ("datamate_search", {"threshold": 0.6}, True),
    ("ragflow_search", {"similarity_threshold": -0.1}, False),
    ("idata_search", {"similarity_threshold": -10}, True),
    ("haotian_search", {"score_threshold": None}, True),
    ("deepseek_search", {"max_results": 50}, True),
    ("deepseek_search", {"max_results": 51}, False),
    ("exa_search", {"max_results": 100}, True),
    ("dify_search", {"top_k": None}, False),
    ("ind_aidp_search", {"top_k": 7}, False),
])
def test_search_override_rules_follow_the_tool(name, values, accepted):
    from contracts.agentos import LocalSearchOverrides
    from infrastructure.local_tool_execution import LOCAL_SDK_TOOL_CLASSES, apply_local_search_overrides

    tool = ToolConfig(name=name, class_name=LOCAL_SDK_TOOL_CLASSES[name], params={"api_key": "stored"})
    overrides = LocalSearchOverrides.model_validate(values)

    if accepted:
        assert apply_local_search_overrides(tool, overrides).params == {"api_key": "stored", **values}
    else:
        with pytest.raises(ValueError):
            apply_local_search_overrides(tool, overrides)
    assert tool.params == {"api_key": "stored"}


def test_local_tool_export_rejects_request_overrides(stored_tool):
    from management.services.agent.preparation import local_tool

    params = {item["name"]: item["default"] for item in stored_tool["params"]}
    tool = ToolConfig(
        class_name="DifySearchTool", name="dify_search", description="Search", output_type="string",
        source="local", params=params | {"top_k": 2, "api_key": "request-only-key"},
    )
    with pytest.raises(ValueError):
        local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_change", [None, "user", "tenant", "agent", "version", "revision", "tampered"])
async def test_request_connection_overrides_use_an_encrypted_scoped_reference(mocker, stored_tool, scope_change):
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import local_tool, tools
    from runtime.agentos import prepared_local_tool

    overrides = {"server_url": "https://request-private.invalid/v1", "api_key": "request-private-secret"}
    # The compiler receives effective instance defaults from its bound-tool query.
    params = [{**item, "default": 2} if item["name"] == "top_k" else item for item in stored_tool["params"]]
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[{**stored_tool, "params": params}])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "agent"})
    tool, = await tools.create_tool_config_list(
        7, "tenant-a", "user-a", version_no=3, portable_evaluation=True,
        tool_params={"agents": {"agent": {"tools": {"dify_search": overrides}}}},
    )
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    exported = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh", user_id="user-a")
    encoded = exported.model_dump_json()
    for value in (*overrides.values(), "local-only-dify-key", "private-dify.invalid"):
        assert value not in encoded
    assert exported.credential_ref
    resource = SimpleNamespace(agent_id=7, version_no=3, tools=[ToolBinding.model_validate_json(encoded)])
    actor = ServicePrincipal("user-a", "tenant-a")
    rows = [stored_tool]
    if scope_change == "user":
        actor = ServicePrincipal("other-user", "tenant-a")
    elif scope_change == "tenant":
        actor = ServicePrincipal("user-a", "other-tenant")
    elif scope_change == "agent":
        resource.agent_id = 8
    elif scope_change == "version":
        resource.version_no = 4
    elif scope_change == "revision":
        rows = [{**stored_tool, "instance_params": {"top_k": 8}}]
    elif scope_change == "tampered":
        reference = resource.tools[0].credential_ref
        resource.tools[0].credential_ref = reference[:80] + ("A" if reference[80] != "A" else "B") + reference[81:]
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=rows)
    hydrate = mocker.patch.object(prepared_local_tool, "_reranker")
    if scope_change:
        with pytest.raises((HTTPException, ValueError)):
            prepared_local_tool.materialize_local_tools(resource, actor, "zh")
        hydrate.assert_not_called()
    else:
        rebound = prepared_local_tool.materialize_local_tools(resource, actor, "zh")["dify_search"]
        assert rebound.params == build_local_tool(stored_tool, "zh", None, None).params | overrides
        assert rebound.metadata["rerank_model"] is hydrate.return_value


def test_nested_agent_snapshot_retains_request_parameter_owner(mocker, stored_tool):
    from contracts.agentos import PreparedEvaluationRun
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.local_tool_execution import LOCAL_PARAMETER_OVERRIDES_METADATA, build_local_tool
    from management.services.agent import tool_identity
    from management.services.agent.preparation import evaluation_snapshot, local_tool
    from nexent.core.agents.agent_model import AgentConfig
    from runtime.agentos import prepared_local_tool
    from test.backend.app.test_agentos_prepared_evaluation import model_record

    parameters = {"api_key": "nested-request-only-key"}
    tool = build_local_tool(stored_tool, "zh", None, None)
    tool.params.update(parameters)
    tool.metadata = {LOCAL_PARAMETER_OVERRIDES_METADATA: parameters}
    record = model_record(model_id=11)
    model = create_model_config_from_record(record)
    child = AgentConfig(
        agent_id=8, version_no=4, name="child", description="child", model_name=model.cite_name, tools=[tool],
    )
    root = AgentConfig(
        agent_id=7, version_no=3, name="root", description="root", model_name=model.cite_name,
        tools=[], worker_agents=[child],
    )
    mocker.patch.object(evaluation_snapshot, "read_bound_local_tools", return_value=[stored_tool])
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    mocker.patch.object(tool_identity, "resolve_tool_user_context", return_value={})
    snapshot = evaluation_snapshot.export_snapshot(
        root, [model], "hello", None, user_id="user-a", tenant_id="tenant-a", conversation_id=None, language="zh",
    )
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    assert parameters["api_key"] not in encoded
    restored = PreparedEvaluationRun.model_validate_json(encoded)
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[stored_tool])
    mocker.patch.object(prepared_local_tool, "_reranker")
    rebuilt = prepared_local_tool.materialize_local_tools(
        restored.resource.subagents[0], ServicePrincipal("user-a", "tenant-a"), "zh",
    )
    assert rebuilt["dify_search"].params["api_key"] == parameters["api_key"]


def test_local_deepseek_reconstruction_uses_runtime_language(mocker, stored_tool):
    from infrastructure.local_tool_execution import build_local_tool, local_tool_revision
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    row = {
        **stored_tool, "name": "deepseek_search", "class_name": "DeepSeekSearchTool",
        "params": [
            {"name": "api_key", "default": "fixture-only-key"},
            {"name": "localization", "default": "en"},
            {"name": "max_content_chars", "default": 200},
            {"name": "language", "default": "en"},
        ],
    }
    tool = build_local_tool(row, "zh", None, None)
    assert tool.params == {"api_key": "fixture-only-key", "language": "zh"}
    binding = local_tool.export_local_tool(tool, [row], 7, 3, "tenant-a", "zh")
    assert binding.parameters["revision"] == local_tool_revision("tenant-a", 7, 3, row, tool)
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    with pytest.raises(HTTPException) as error:
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "en",
        )
    assert error.value.status_code == 409


def test_local_tool_credential_override_is_rejected_before_repository_access(mocker):
    from runtime.agentos import prepared_local_tool

    lookup = mocker.patch.object(prepared_local_tool, "read_bound_local_tools")
    binding = ToolBinding(tool_id="dify_search", version="1", credential_ref="injected")
    with pytest.raises(ValueError, match="Unsupported local SDK tool binding"):
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "zh",
        )
    lookup.assert_not_called()


@pytest.mark.parametrize(("change", "status"), [
    (None, None), ("scope", 409), ("sources", 409), ("parameters", 409), ("conflict", 409), ("shadowed", 404),
])
def test_skill_derived_local_tool_is_pinned_to_authorized_contributors(mocker, stored_tool, change, status):
    from contracts.errors.exceptions import ValidationError
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    row = {
        **{key: value for key, value in stored_tool.items() if key != "tool_instance_id"},
        "skill_instance_ids": [5, 6], "instance_params": {},
    }
    tool = build_local_tool(row, "zh", None, None)
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(tool, [row], 7, 3, "tenant-a", "zh")
    assert binding.version == "2"
    assert binding.parameters["tool_id"] == 10
    assert "local-only-dify-key" not in binding.model_dump_json()
    explicit = mocker.patch.object(prepared_local_tool, "read_bound_local_tools")
    derived = mocker.patch.object(prepared_local_tool, "read_skill_derived_local_tools", return_value=[row])
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")
    scope = [SimpleNamespace(instance_id=5), SimpleNamespace(instance_id=6)]
    resource = SimpleNamespace(agent_id=7, version_no=3, tools=[binding], skill_refs=scope)
    actor = ServicePrincipal("user-a", "tenant-a")

    if change == "scope":
        scope.pop()
    elif change == "sources":
        derived.return_value = [{**row, "skill_instance_ids": [5]}]
    elif change == "parameters":
        derived.return_value = [{**row, "params": [*row["params"], {"name": "search_method", "default": "keyword_search"}]}]
    elif change == "conflict":
        derived.side_effect = ValidationError("synthetic conflict")
    elif change == "shadowed":
        derived.return_value = []

    if status is None:
        rebound = prepared_local_tool.materialize_local_tools(resource, actor, "zh")[tool.name]
        assert rebound.params == tool.params
        assert rebound.metadata["rerank_model"] is hydrate_rerank.return_value
    else:
        with pytest.raises(HTTPException) as error:
            prepared_local_tool.materialize_local_tools(resource, actor, "zh")
        assert error.value.status_code == status
        hydrate_rerank.assert_not_called()

    explicit.assert_not_called()
    derived.assert_called_once_with(7, 3, "tenant-a", ["dify_search"])


@pytest.mark.parametrize(("name", "class_name"), [
    ("create_file", "CreateFileTool"), ("read_file", "ReadFileTool"), ("delete_file", "DeleteFileTool"),
    ("create_directory", "CreateDirectoryTool"), ("delete_directory", "DeleteDirectoryTool"),
    ("list_directory", "ListDirectoryTool"), ("move_item", "MoveItemTool"), ("terminal", "TerminalTool"),
])
def test_workspace_and_ssh_tools_restore_persisted_parameters_without_exposing_them(
    mocker, stored_tool, tmp_path, name, class_name,
):
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    params = {"init_path": str(tmp_path)}
    if name == "terminal":
        params.update(ssh_host="runtime-ssh.invalid", ssh_user="runner", password="private-ssh-key")
    row = {
        **stored_tool, "name": name, "class_name": class_name, "instance_params": {},
        "params": [{"name": key, "default": value} for key, value in params.items()],
    }
    config = build_local_tool(row, "en", None, None)
    binding = local_tool.export_local_tool(config, [row], 7, 3, "tenant-a", "en")
    encoded = binding.model_dump_json()
    for value in params.values():
        assert json.dumps(value)[1:-1] not in encoded
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    resource = SimpleNamespace(agent_id=7, version_no=3, tools=[binding])
    rebound = prepared_local_tool.materialize_local_tools(resource, ServicePrincipal("user-a", "tenant-a"), "en")[name]
    tool = NexentAgent.create_local_tool(SimpleNamespace(observer=None), rebound)

    assert type(tool).__name__ == class_name
    assert tool.init_path == str(tmp_path)
    if name == "create_file":
        tool.forward("prepared.txt", "AgentOS file")
        assert (tmp_path / "prepared.txt").read_text(encoding="utf-8") == "AgentOS file"
    elif name == "terminal":
        assert (tool.ssh_host, tool.ssh_user, tool.password) == ("runtime-ssh.invalid", "runner", "private-ssh-key")
