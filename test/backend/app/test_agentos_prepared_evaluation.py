# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos.prepared_evaluation import prepare_evaluation_run


@pytest.fixture(autouse=True)
def local_sandbox(monkeypatch):
    monkeypatch.setattr("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")


def evaluation_payload():
    return {
        "mode": "nexent",
        "resource": {
            "agent_id": 7, "version_no": 2, "name": "test_agent",
            "description": "Evaluation agent", "prompt_templates": {"system_prompt": "Answer the query"},
        },
        "models": {"llm": {"model_id": 11, "alias": "evaluation_llm", "revision": "revision-1"}},
        "input": {"query": "hello", "history": [{"role": "user", "content": "earlier"}]},
        "conversation_id": -10,
    }


def test_prepared_case_round_trip_and_forbidden_fields():
    payload = evaluation_payload()
    model = PreparedEvaluationRun.model_validate(payload)
    assert PreparedEvaluationRun.model_validate_json(model.model_dump_json()) == model

    payload["models"]["llm"]["api_key"] = "should-not-cross"
    with pytest.raises(ValidationError, match="api_key"):
        PreparedEvaluationRun.model_validate(payload)


@pytest.mark.parametrize("conversation_id", [1, "0", True])
def test_prepared_case_rejects_real_or_coerced_conversation_ids(conversation_id):
    with pytest.raises(ValidationError, match="conversation_id"):
        PreparedEvaluationRun.model_validate(evaluation_payload() | {"conversation_id": conversation_id})


def model_record(**changes):
    return {
        "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm", "model_name": "provider-model",
        "model_repo": None, "display_name": "Evaluation", "api_key": "runtime-only",
        "base_url": "https://runtime-provider.example/v1", "update_time": "revision-1",
    } | changes


@pytest.mark.parametrize("target", ["evaluation", "subagent", "workbench"])
def test_runtime_rejects_native_generation_outside_a_native_root(mocker, target):
    from contracts.agentos import PreparedAgentRun
    from runtime.agentos.prepared_evaluation import prepare_run_snapshot

    raw = evaluation_payload()
    models = raw["models"]
    generation = {"settings": {"temperature": 0.4}}
    if target == "subagent":
        models["additional_llms"] = [{**models["llm"], "alias": "child", "turn_generation": generation}]
    else:
        models["llm"]["turn_generation"] = generation
    if target == "evaluation":
        payload = PreparedEvaluationRun.model_validate(raw)
    else:
        if target == "workbench":
            raw["workbench_config_version"] = 1
            models["llm"]["root_generation"] = {"temperature": 0.3}
        raw.update(conversation_id=42, run_id="a" * 32)
        payload = PreparedAgentRun.model_validate(raw)
    load = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id")

    with pytest.raises(HTTPException) as error:
        prepare_run_snapshot(payload, ServicePrincipal("user-a", "tenant-a"))

    assert error.value.status_code == 422
    load.assert_not_called()


def test_runtime_materializes_authorized_model_and_local_objects(mocker):
    load_record = mocker.patch(
        "runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_record(),
    )
    actor = ServicePrincipal("user-a", "tenant-a")
    info = prepare_evaluation_run(PreparedEvaluationRun.model_validate(evaluation_payload()), actor)

    load_record.assert_called_once_with(11, "tenant-a")
    assert info.tenant_id == "tenant-a" and info.user_id == "user-a"
    assert info.conversation_id == -10 and info.query == "hello"
    assert info.agent_config.model_name == "evaluation_llm"
    assert info.model_config_list[0].api_key == "runtime-only"
    assert not info.stop_event.is_set()
    assert info.history[0].content == "earlier"


@pytest.mark.parametrize(("change", "status"), [
    ({"tenant_id": "tenant-b"}, 404), ({"delete_flag": "Y"}, 404),
    ({"update_time": "revision-2"}, 409), ({"model_type": "embedding"}, 422),
])
def test_runtime_rejects_unavailable_model_before_constructing_sdk_objects(mocker, change, status):
    from fastapi import HTTPException

    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_record(**change))
    build = mocker.patch("runtime.agentos.prepared_evaluation.materialize_run", new=MagicMock())

    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(
            PreparedEvaluationRun.model_validate(evaluation_payload()), ServicePrincipal("user-a", "tenant-a"),
        )

    assert error.value.status_code == status
    build.assert_not_called()


@pytest.mark.parametrize("change", [
    {"tools": [{"tool_id": "download", "version": "1"}]},
    {"sandbox_policy": {"level": "unsupported"}},
    {"memory_ref": "some-memory"},
])
def test_runtime_rejects_unsupported_resources_before_model_lookup(mocker, change):
    from fastapi import HTTPException

    lookup = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id")
    payload = evaluation_payload()
    payload["resource"].update(change)

    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(PreparedEvaluationRun.model_validate(payload), ServicePrincipal("user-a", "tenant-a"))

    assert error.value.status_code == 422
    assert error.value.detail == {"code": "AGENTOS_RESOURCE_UNSUPPORTED"}
    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_keeps_run_registered_until_worker_exits(mocker):
    import asyncio
    from concurrent.futures import Future

    from runtime.agentos import prepared_evaluation
    from runtime.executions import LocalExecutionRegistry

    actor = ServicePrincipal("user-a", "tenant-a")
    payload = PreparedEvaluationRun.model_validate(evaluation_payload())
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model_record())
    info = prepare_evaluation_run(payload, actor)
    future = Future()
    info.thread_future = future
    mocker.patch.object(prepared_evaluation, "run_blocking", return_value=info)
    registry = LocalExecutionRegistry()
    mocker.patch.object(prepared_evaluation, "agent_run_manager", registry)
    unregister = mocker.patch.object(registry, "unregister_agent_run", wraps=registry.unregister_agent_run)
    mocker.patch.object(prepared_evaluation, "collect_observer_output", side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await prepared_evaluation.execute_prepared_evaluation(payload, actor)

    assert registry.get_agent_run_info(-10, actor.user_id) is info
    unregister.assert_not_called()
    future.set_result(None)
    assert registry.get_agent_run_info(-10, actor.user_id) is None
    unregister.assert_called_once_with(-10, actor.user_id, status="stopped", agent_run_info=info)


def test_exported_builtin_binding_reconstructs_run_scope_without_transmitting_clients(mocker):
    from nexent.core.agents.agent_model import AgentConfig, ToolConfig
    from nexent.core.agents.context import ContextManagerConfig
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation.evaluation_snapshot import export_snapshot

    record = model_record(model_id=11)
    model = create_model_config_from_record(record)
    agent = AgentConfig(
        agent_id=7, version_no=2, name="test_agent", description="Evaluation agent",
        model_name=model.cite_name, prompt_templates={"system_prompt": "original"},
        tools=[ToolConfig(
            class_name="DownloadFromS3Tool", name="download_from_s3", source="builtin", usage="builtin",
            params={"workspace_path": "/management/workspace"},
            metadata={"minio_client": object(), "validate_url_access": lambda _: None, "user_id": "other"},
        )],
        context_manager_config=ContextManagerConfig(token_threshold=1234),
    )
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[record])
    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=record)

    payload = export_snapshot(agent, [model], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")

    assert payload is not None
    assert "runtime-only" not in payload.model_dump_json()
    assert "/management/workspace" not in payload.model_dump_json()
    info = prepare_evaluation_run(payload, ServicePrincipal("user-a", "tenant-a"))
    tool = info.agent_config.tools[0]
    assert tool.class_name == "DownloadFromS3Tool"
    assert tool.metadata["user_id"] == "user-a"
    assert tool.metadata["tenant_id"] == "tenant-a"
    assert tool.params["workspace_path"] == info.workspace_path
    assert info.agent_config.context_manager_config.token_threshold == 1234
    tool.metadata["validate_url_access"](["s3://bucket/attachments/user-a/allowed.txt"])
    with pytest.raises(PermissionError):
        tool.metadata["validate_url_access"](["s3://bucket/attachments/user-b/denied.txt"])

    assert export_snapshot(
        agent, [model.model_copy(update={"api_key": "management-only"})], "hello", None,
        tenant_id="tenant-a", conversation_id=-42, language="en",
    ) is None


def test_exported_child_with_separate_model_and_explicit_overrides_round_trips(mocker):
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation.evaluation_snapshot import export_snapshot
    from nexent.core.agents.agent_model import AgentConfig

    records = {
        11: model_record(model_id=11, display_name="root_model"),
        12: model_record(model_id=12, display_name="child_model", api_key="child-secret"),
    }
    models = [create_model_config_from_record(record) for record in records.values()]
    models[1] = models[1].model_copy(update={"temperature": 0.11, "enable_thinking": False, "reasoning_effort": "low"})
    child = AgentConfig(
        agent_id=2, version_no=3, name="child", invocation_name="fetch_details",
        runtime_ref="agent:2:v3", model_name="child_model", description="child", tools=[],
    )
    root = AgentConfig(
        agent_id=1, version_no=4, name="root", model_name="root_model", description="root", tools=[],
        worker_agents=[child],
    )
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", side_effect=(
        lambda filters, tenant: [record for record in records.values() if record["display_name"] == filters["display_name"]]
    ))
    lookup = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id",
                          side_effect=lambda model_id, tenant: records[model_id])
    snapshot = export_snapshot(root, models, "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    assert "child-secret" not in encoded and "runtime-only" not in encoded and "base_url" not in encoded
    restored = PreparedEvaluationRun.model_validate_json(encoded)
    overrides = restored.models.additional_llms[0].overrides
    assert overrides.model_dump(exclude_unset=True) == {"temperature": 0.11, "reasoning_effort": "low"}

    info = prepare_evaluation_run(restored, ServicePrincipal("user-a", "tenant-a"))
    assert [call.args for call in lookup.call_args_list] == [(11, "tenant-a"), (12, "tenant-a")]
    assert info.model_config_list == models
    rebuilt = info.agent_config.worker_agents[0]
    assert (rebuilt.agent_id, rebuilt.version_no, rebuilt.invocation_name, rebuilt.runtime_ref, rebuilt.model_name) == (
        2, 3, "fetch_details", "agent:2:v3", "child_model",
    )


@pytest.mark.parametrize("invalid", [{"api_key": "secret"}, {"temperature": 3.0}, {"enable_thinking": None}])
def test_snapshot_rejects_unapproved_overrides(invalid):
    payload = evaluation_payload()
    payload["models"]["llm"]["overrides"] = invalid
    with pytest.raises(ValidationError, match="overrides"):
        PreparedEvaluationRun.model_validate(payload)


def test_model_override_keeps_explicit_clear_and_false_through_json():
    payload = evaluation_payload()
    payload["models"]["llm"]["overrides"] = {"enable_thinking": False, "reasoning_effort": None}
    encoded = PreparedEvaluationRun.model_validate(payload).model_dump_json()
    restored = PreparedEvaluationRun.model_validate_json(encoded)
    assert restored.models.llm.overrides.model_dump() == {"enable_thinking": False, "reasoning_effort": None}


@pytest.mark.parametrize("invalid", ["duplicate", "missing", "wrong_root", "unused"])
def test_runtime_rejects_inconsistent_tree_model_bindings(mocker, invalid):
    from fastapi import HTTPException

    lookup = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id")
    payload = evaluation_payload()
    child = payload["resource"].copy()
    child.update(agent_id=8, model_alias="child_llm")
    if invalid == "duplicate":
        payload["models"]["additional_llms"] = [payload["models"]["llm"].copy()]
    elif invalid == "missing":
        payload["resource"]["subagents"] = [child]
    elif invalid == "wrong_root":
        payload["resource"]["model_alias"] = "child_llm"
    else:
        payload["models"]["additional_llms"] = [{"model_id": 12, "alias": "child_llm", "revision": "r2"}]
    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(PreparedEvaluationRun.model_validate(payload), ServicePrincipal("user-a", "tenant-a"))
    assert error.value.status_code == 422
    lookup.assert_not_called()


@pytest.mark.parametrize(("record_change", "status"), [
    ({"tenant_id": "tenant-b"}, 404),
    ({"update_time": "changed-child-revision"}, 409),
])
def test_runtime_rejects_child_model_scope_or_revision_before_worker_creation(mocker, record_change, status):
    from fastapi import HTTPException

    payload = evaluation_payload()
    payload["resource"]["subagents"] = [payload["resource"].copy() | {"agent_id": 8, "model_alias": "child_llm"}]
    payload["models"]["additional_llms"] = [{"model_id": 12, "alias": "child_llm", "revision": "revision-1"}]
    lookup = mocker.patch(
        "runtime.agentos.prepared_evaluation.get_model_by_model_id",
        side_effect=[model_record(), model_record(**record_change)],
    )
    build = mocker.patch("runtime.agentos.prepared_evaluation.materialize_run")

    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(PreparedEvaluationRun.model_validate(payload), ServicePrincipal("user-a", "tenant-a"))

    assert error.value.status_code == status
    assert [call.args for call in lookup.call_args_list] == [(11, "tenant-a"), (12, "tenant-a")]
    build.assert_not_called()


@pytest.mark.parametrize(("change", "expected"), [
    ("none", None), ("unlinked", 404), ("tenant", 404),
    ("credentials", 409), ("endpoint", 409), ("duplicate", 422),
])
def test_external_a2a_binding_rebuilds_only_authorized_revision(mocker, change, expected):
    from fastapi import HTTPException

    from infrastructure.a2a_execution import build_external_agent_config
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation.evaluation_snapshot import export_snapshot
    from nexent.core.agents.agent_model import AgentConfig

    mocker.patch("contracts.constants.environment.JWT_SECRET", "synthetic-agentos-a2a-key")
    row = {
        "external_agent_id": 19, "name": "Peer", "description": "External peer",
        "agent_url": "https://external.example/private-endpoint",
        "security_schemes": {"auth": {"scheme": "Bearer"}},
        "security_requirements": [{"schemes": {"auth": []}}],
        "security_credentials": {"auth": "credential-stays-in-runtime"},
        "raw_card": {"skills": [{"name": "Peer skill"}]},
    }
    configured = build_external_agent_config(row, row["agent_url"]).model_copy(update={"invocation_name": "remote_peer"})
    model_row = model_record(model_id=11)
    model = create_model_config_from_record(model_row)
    child = AgentConfig(
        agent_id=7, version_no=2, name="child", description="", tools=[], model_name=model.cite_name,
        external_a2a_agents=[configured],
    )
    root = AgentConfig(
        agent_id=8, version_no=1, name="root", description="", tools=[], model_name=model.cite_name,
        worker_agents=[child],
    )
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[model_row])
    snapshot = export_snapshot(root, [model], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    for sensitive in (row["agent_url"], "credential-stays-in-runtime", "raw_card", "security_credentials", "custom_headers"):
        assert sensitive not in encoded
    restored = PreparedEvaluationRun.model_validate_json(encoded)
    model_lookup = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_row)
    tenant = "tenant-b" if change == "tenant" else "tenant-a"
    rows = {19: row}
    if change in {"unlinked", "tenant"}:
        rows = {}
    elif change == "credentials":
        rows = {19: row | {"security_credentials": {"auth": "rotated"}}}
    elif change == "endpoint":
        rows = {19: row | {"agent_url": "https://replacement.example"}}
    elif change == "duplicate":
        restored.resource.subagents[0].external_a2a *= 2
    reader = mocker.patch("runtime.agentos.prepared_evaluation.read_external_agent_bindings", return_value=rows)

    if expected is None:
        info = prepare_evaluation_run(restored, ServicePrincipal("user-a", tenant))
        assert info.agent_config.worker_agents[0].external_a2a_agents == [configured]
        model_lookup.assert_called_once_with(11, tenant)
    else:
        with pytest.raises(HTTPException) as error:
            prepare_evaluation_run(restored, ServicePrincipal("user-a", tenant))
        assert error.value.status_code == expected
        model_lookup.assert_not_called()
    if change == "duplicate":
        reader.assert_not_called()
    else:
        reader.assert_called_once_with(7, tenant, [19])


@pytest.mark.parametrize(("change", "status"), [
    ("remote", None), ("local", None), ("revoked", 404), ("disabled", 404), ("rotated", 409), ("params", 409),
    ("override", None), ("override_rotated", 409), ("override_params", 409), ("unknown_override", None),
    ("wire_unknown_override", 422),
])
@pytest.mark.asyncio
async def test_mcp_snapshot_rebuilds_only_the_signed_agent_version_and_server(mocker, change, status):
    from fastapi import HTTPException

    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.mcp_execution import build_mcp_tool
    from management.services.agent.preparation import tools
    from management.services.agent.preparation.evaluation_snapshot import export_snapshot
    from nexent.core.agents.agent_model import AgentConfig

    mocker.patch("contracts.constants.environment.JWT_SECRET", "synthetic-agentos-mcp-key")
    mocker.patch("contracts.constants.environment.LOCAL_MCP_SERVER", "http://local-mcp.example")
    mocker.patch("contracts.constants.environment.TOKEN", "runtime-internal-token")
    tool_row = {
        "tool_instance_id": 17, "name": "lookup", "class_name": "lookup", "origin_name": "lookup",
        "description": "Lookup", "inputs": None, "output_type": "object",
        "usage": "outer-apis" if change == "local" else "remote",
        "params": [{"name": "private_param", "default": "default-tool-param"}, {"name": "limit", "default": 3}],
        "instance_params": {"private_param": "stored-tool-param"},
    }
    server = {
        "mcp_id": 29, "mcp_name": "remote", "mcp_server": "https://remote.example/private",
        "authorization_token": "remote-token", "custom_headers": {"X-Key": "remote-key"}, "enabled": True,
    }
    model_row = model_record(model_id=11)
    model = create_model_config_from_record(model_row)
    overrides = change.startswith("override")
    compiled = [build_mcp_tool(tool_row)]
    if overrides or change == "unknown_override":
        definition = {**tool_row, "source": "mcp", "params": [
            {**param, "default": tool_row["instance_params"].get(param["name"], param["default"])}
            for param in tool_row["params"]
        ]}
        mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[definition])
        mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "agent"})
        parameters = {"limit": 8} if overrides else {"connection_header": "not-a-tool-argument"}
        compiled = await tools.create_tool_config_list(
            7, "tenant-a", "user-a", version_no=2, portable_evaluation=True,
            tool_params={"agents": {"agent": {"tools": {"lookup": parameters}}}},
        )
    config = AgentConfig(
        agent_id=7, version_no=2, name="agent", description="", model_name=model.cite_name,
        tools=compiled,
    )
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[model_row])
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.read_bound_mcp_tools", return_value=[tool_row])
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.read_mcp_execution_servers", return_value=[server])
    mocker.patch("management.services.agent.tool_identity.resolve_tool_user_context", return_value={
        "tenant_name": "Tenant A", "user_groups": ["Support"], "tenant_id": "ignored", "user_id": "ignored",
    })
    snapshot = export_snapshot(config, [model], "hello", None, tenant_id="tenant-a",
                               user_id="user-a", conversation_id=-42, language="en")
    if change == "unknown_override":
        assert snapshot is None
        return
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    for value in (server["mcp_server"], "remote-token", "remote-key", "stored-tool-param", "runtime-internal-token"):
        assert value not in encoded
    payload = PreparedEvaluationRun.model_validate_json(encoded)
    parameters = payload.resource.tools[0].parameters
    if overrides:
        assert parameters["argument_overrides"] == {"limit": 8}
    else:
        assert "argument_overrides" not in parameters
    if change == "wire_unknown_override":
        parameters["argument_overrides"] = {"connection_header": "not-a-tool-argument"}

    if change in {"rotated", "override_rotated"}:
        server["authorization_token"] = "new-token"
    elif change == "disabled":
        server["enabled"] = False
    elif change == "params":
        tool_row["instance_params"] = {"private_param": "changed"}
    elif change == "override_params":
        tool_row["instance_params"]["limit"] = 10
    reader = mocker.patch("runtime.agentos.prepared_mcp.read_bound_mcp_tools",
                          return_value=[] if change == "revoked" else [tool_row])
    mocker.patch("runtime.agentos.prepared_mcp.read_mcp_execution_servers", return_value=[server])
    model_reader = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_row)
    actor = ServicePrincipal("user-a", "tenant-a")
    if status:
        with pytest.raises(HTTPException) as error:
            prepare_evaluation_run(payload, actor)
        assert error.value.status_code == status
        model_reader.assert_not_called()
    else:
        info = prepare_evaluation_run(payload, actor)
        assert info.agent_config.tools[0].params == {"private_param": "stored-tool-param", "limit": 8 if overrides else 3}
        host, = info.mcp_host
        assert host["allowed_tools"] == {"lookup": "lookup"}
        if change == "local":
            assert host["url"] == "http://local-mcp.example/mcp/tenant-a/sse"
            assert host["headers"] == {"X-Tenant-ID": "tenant-a", "X-Nexent-Internal-Token": "runtime-internal-token"}
            assert callable(host["httpx_client_factory"])
        else:
            assert host["headers"] == {"Authorization": "remote-token", "X-Key": "remote-key"}
        assert info.user_context["user_id"] == "user-a"
        assert info.user_context["tenant_id"] == "tenant-a"
        assert info.user_context["user_groups"] == ["Support"]
    reader.assert_called_once_with(7, 2, "tenant-a", ["lookup"])


@pytest.mark.parametrize("level", ["local", "docker"])
def test_prepared_evaluation_rebuilds_executor_context_from_runtime_settings(mocker, tmp_path, level):
    from contracts.constants import environment
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation.evaluation_snapshot import export_snapshot
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer

    record = model_record(model_id=11)
    selected = create_model_config_from_record(record)
    agent = AgentConfig(
        agent_id=7, version_no=2, name="evaluation", description="", model_name=selected.cite_name, tools=[],
        context_items=[{
            "id": "system:restricted_python_execution", "type": "system", "content": {"text": "management-only"},
            "metadata": {"authority": "platform", "layout_order": 32},
        }],
    )
    mocker.patch("management.services.agent.preparation.evaluation_snapshot.get_model_records", return_value=[record])
    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=record)
    mocker.patch("runtime.agentos.prepared_evaluation.AGENT_WORKSPACE_ROOT", str(tmp_path))
    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", level)
    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_SCOPE", "system")
    mocker.patch.object(environment, "NEXENT_SANDBOX_WORKSPACE_MODE", "legacy")
    mocker.patch.object(environment, "NEXENT_SANDBOX_WORKSPACE_VOLUME", "runtime-managed-volume")
    mocker.patch.object(environment, "NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS", True)
    client = mocker.patch("runtime.adapters.nexent.factory.get_sandbox_minio_client")

    prepared = export_snapshot(agent, [selected], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en")
    assert prepared is not None
    assert prepared.resource.evaluation_options.render_executor_context
    assert "management-only" not in prepared.model_dump_json()
    info = prepare_evaluation_run(prepared, ServicePrincipal("user-a", "tenant-a"))

    composer = AgentPromptComposer(AgentPromptBundle.from_resource(role="managed", language="en"))
    hints = [item for item in info.agent_config.context_items if item.metadata.get("layout_order") == 32]
    hint, = hints
    if level == "docker":
        assert info.sandbox_config.level.value == "docker"
        assert info.sandbox_config.extra_kwargs["workspace_volume_name"] == "runtime-managed-volume"
        assert info.sandbox_config.extra_kwargs["workspace_path"] == info.workspace_path
        assert info.sandbox_config.output_dir.endswith("outputs")
        assert info.minio_client is client.return_value
        client.assert_called_once_with()
        assert hint.id == "system:sandbox_workspace_guidance"
        assert hint.content["text"] == composer.render_system_section("sandbox_workspace_guidance")
    else:
        assert info.sandbox_config is None
        client.assert_not_called()
        assert hint.id == "system:restricted_python_execution"


def test_invalid_runtime_sandbox_settings_fail_before_execution(mocker):
    from fastapi import HTTPException
    from contracts.constants import environment

    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "invalid")
    reader = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id")
    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(
            PreparedEvaluationRun.model_validate(evaluation_payload()), ServicePrincipal("user-a", "tenant-a"),
        )
    assert error.value.status_code == 422
    reader.assert_not_called()


@pytest.mark.asyncio
async def test_management_prepares_evaluation_with_nonlocal_deployment_setting(mocker):
    from contracts.agentos import EvaluationAgentRun
    from contracts.constants import environment
    from management.services.agent.preparation import evaluation_snapshot

    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "docker")
    mocker.patch.object(evaluation_snapshot, "NEXENT_SANDBOX_DEFAULT_LEVEL", "docker", create=True)
    compiler = mocker.patch("management.services.agent.preparation.run.create_agent_run_info")
    request = EvaluationAgentRun(agent_id=7, version_no=2, query="hello", conversation_id=-42)
    assert await evaluation_snapshot.prepare_evaluation_snapshot(request, "user-a", "tenant-a") is compiler.return_value
    compiler.assert_awaited_once()
    assert compiler.call_args.kwargs["export_evaluation"] is True


@pytest.mark.parametrize("scope", ["evaluation", "a2a", "child", "debug_child", "missing", "duplicate", "parameters", "credential"])
def test_runtime_rejects_invalid_prepared_planning_before_model_lookup(mocker, scope):
    from fastapi import HTTPException

    from contracts.agentos import PreparedAgentRun, PreparedEphemeralRun
    from runtime.agentos import prepared_evaluation

    payload = evaluation_payload()
    create = {"tool_id": "create_plan", "version": "1"}
    update = {"tool_id": "update_plan_step", "version": "1"}
    tools = [create, update]
    resource = payload["resource"]
    if scope in {"child", "debug_child"}:
        resource["subagents"] = [{**resource, "agent_id": 8, "model_alias": "evaluation_llm", "tools": tools}]
    else:
        resource["tools"] = tools
    if scope == "missing":
        tools.pop()
    if scope == "duplicate":
        tools.append(create.copy())
    if scope == "parameters":
        create["parameters"] = {"extra": 1}
    if scope == "credential":
        create["credential_ref"] = "unexpected"
    if scope == "evaluation":
        prepared = PreparedEvaluationRun.model_validate(payload)
    elif scope in {"a2a", "debug_child"}:
        payload.pop("conversation_id")
        prepared = PreparedEphemeralRun.model_validate({
            **payload, "run_id": "a" * 32, "debug": True if scope == "debug_child" else None,
        })
    else:
        prepared = PreparedAgentRun.model_validate({**payload, "conversation_id": 42, "run_id": "a" * 32})
    read = mocker.patch.object(prepared_evaluation, "get_model_by_model_id")

    with pytest.raises(HTTPException) as error:
        prepared_evaluation.prepare_run_snapshot(prepared, ServicePrincipal("user-a", "tenant-a"))

    assert error.value.status_code == 422
    read.assert_not_called()
