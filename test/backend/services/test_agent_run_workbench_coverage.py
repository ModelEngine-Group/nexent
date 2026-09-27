import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.backend.services import test_agent_service as legacy


agent_run = legacy.agent_run_service
AgentRequest = legacy.AgentRequest


def _request(**overrides):
    values = {
        "agent_id": 1,
        "conversation_id": 123,
        "query": "hello",
        "history": [],
        "minio_files": [],
        "requested_output_tokens": 512,
        "is_debug": False,
    }
    values.update(overrides)
    return AgentRequest(**values)


def test_apply_workbench_runtime_plan_attaches_all_runtime_overrides(monkeypatch):
    request = _request()
    generation_config = MagicMock()
    generation_config.model_dump.return_value = {"temperature": 0.2}
    canonical = SimpleNamespace(
        knowledge_scope={"local": {"knowledge_ids": [7]}},
        generation_config=generation_config,
    )
    identity = SimpleNamespace(
        agent_id=9,
        version_no=3,
        runtime_ref="agent:9:3",
        invocation_name="researcher",
        display_name="Researcher",
        origin="USER",
    )
    plan = SimpleNamespace(
        root=SimpleNamespace(identity=identity),
        overlay=SimpleNamespace(model_id=12, requested_output_tokens=2048),
    )
    knowledge_tree = [{"tools": [{"id": "original"}]}]
    mounted_tools = [{"id": "mounted"}]
    attached_plan = SimpleNamespace(
        root=SimpleNamespace(identity=identity),
        overlay=plan.overlay,
    )

    knowledge_scope = __import__(
        "services.knowledge_scope_service", fromlist=["snapshot_runtime_knowledge_tree"]
    )
    workbench = ModuleType("services.workbench_service")
    runtime_mount = ModuleType("services.runtime_knowledge_mount")
    snapshot = MagicMock(return_value=knowledge_tree)
    mount = MagicMock(return_value=mounted_tools)
    attach = MagicMock(return_value=attached_plan)
    skill_snapshot = MagicMock(return_value={"9": ["skill-a"]})
    monkeypatch.setattr(
        knowledge_scope, "snapshot_runtime_knowledge_tree", snapshot, raising=False
    )
    workbench.attach_runtime_knowledge_tree = attach
    workbench.runtime_skill_snapshot = skill_snapshot
    runtime_mount.mount_knowledge_records = mount
    monkeypatch.setitem(sys.modules, "services.workbench_service", workbench)
    monkeypatch.setitem(sys.modules, "services.runtime_knowledge_mount", runtime_mount)

    agent_run.apply_workbench_runtime_plan(request, canonical, plan, "tenant-a")

    snapshot.assert_called_once_with(9, "tenant-a", 3)
    mount.assert_called_once_with(
        [{"id": "original"}], canonical.knowledge_scope, "tenant-a"
    )
    attach.assert_called_once_with(plan, [{"tools": mounted_tools}])
    assert request.workbench is canonical
    assert request.agent_id == 9
    assert request.version_no == 3
    assert request.model_id == 12
    assert request.requested_output_tokens == 2048
    assert request.knowledge_scope == canonical.knowledge_scope
    assert request.__dict__["_runtime_knowledge_tools"] == mounted_tools
    assert request.__dict__["_runtime_skill_snapshot"] == {"9": ["skill-a"]}
    assert request.__dict__["_runtime_mount_plan"] is attached_plan
    assert request.__dict__["_runtime_root_identity"] == {
        "agent_id": 9,
        "version_no": 3,
        "runtime_ref": "agent:9:3",
        "invocation_name": "researcher",
        "display_name": "Researcher",
        "origin": "USER",
    }
    assert request.__dict__["_runtime_generation_config"] == {"temperature": 0.2}


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_generation", [True, False])
async def test_prepare_agent_run_forwards_workbench_runtime_state(
    monkeypatch, stored_generation
):
    from consts.model import WorkbenchGenerationConfig

    request = _request()
    request.__dict__["_runtime_knowledge_context"] = {"policy": "strict"}
    request.__dict__["_runtime_knowledge_tools"] = [{"id": "knowledge"}]
    request.__dict__["_runtime_skill_snapshot"] = {"1": ["skill-a"]}
    if stored_generation:
        request.__dict__["_runtime_generation_config"] = {"temperature": 0.1}
    else:
        request.generation_config = WorkbenchGenerationConfig(temperature=0.1)
    child = SimpleNamespace(
        agent_id=2,
        version_no=4,
        runtime_ref="agent:2:4",
        invocation_name="writer",
        display_name="Writer",
    )
    request.__dict__["_runtime_mount_plan"] = SimpleNamespace(child_mounts=[child])
    request.__dict__["_runtime_metadata_snapshot"] = {"ticket": "NEX-1"}
    request.__dict__["_runtime_metadata_version"] = 6

    run_info = MagicMock()
    original_config = MagicMock()
    original_config.context_items = []
    original_config.context_manager_config = None
    run_info.agent_config = original_config
    run_info.history = []
    executable_config = MagicMock()
    executable_config.context_items = []
    executable_config.context_manager_config = None
    executable_tree = SimpleNamespace(root=SimpleNamespace(agent_config=executable_config))
    create_run = AsyncMock(return_value=run_info)
    register = MagicMock()

    monkeypatch.setattr(agent_run, "build_memory_context", MagicMock(return_value="memory"))
    monkeypatch.setattr(agent_run, "create_agent_run_info", create_run)
    monkeypatch.setattr(agent_run, "get_current_run_user_message_id", MagicMock(return_value=None))
    monkeypatch.setattr(agent_run, "build_authorized_context_input", MagicMock(return_value="context"))
    monkeypatch.setattr(agent_run.agent_run_manager, "register_agent_run", register)
    workbench = ModuleType("services.workbench_service")
    compile_plan = MagicMock(return_value=executable_tree)
    workbench.compile_runtime_mount_plan = compile_plan
    monkeypatch.setitem(sys.modules, "services.workbench_service", workbench)

    result, memory = await agent_run.prepare_agent_run(
        request,
        user_id="user-a",
        tenant_id="tenant-a",
        reservation_token="reservation-a",
    )

    kwargs = create_run.await_args.kwargs
    assert kwargs["runtime_knowledge_context"] == {"policy": "strict"}
    assert kwargs["runtime_knowledge_tools"] == [{"id": "knowledge"}]
    assert kwargs["runtime_skill_snapshot"] == {"1": ["skill-a"]}
    assert kwargs["runtime_generation_config"]["temperature"] == 0.1
    assert kwargs["runtime_sub_agent_mounts"] == [
        {
            "agent_id": 2,
            "version_no": 4,
            "runtime_ref": "agent:2:4",
            "invocation_name": "writer",
            "display_name": "Writer",
        }
    ]
    compile_plan.assert_called_once_with(request.__dict__["_runtime_mount_plan"], original_config)
    assert result.agent_config is executable_config
    assert result.runtime_metadata == {"ticket": "NEX-1"}
    assert result.runtime_metadata_version == 6
    assert result.context_input == "context"
    assert result.conversation_id == 123
    assert result.user_id == "user-a"
    register.assert_called_once_with(
        123, result, "user-a", reservation_token="reservation-a"
    )
    assert memory == "memory"


@pytest.mark.asyncio
async def test_run_agent_stream_resolves_and_persists_existing_workbench(monkeypatch):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    canonical = WorkbenchSessionConfig.model_validate(
        {
            "mode": "single_agent_chat",
            "agent_mounts": [{"agent_id": 7, "version_no": 3}],
        }
    )
    request = _request(
        entrypoint="workbench",
        workbench=None,
        expected_workbench_config_version=2,
    )
    conversation = {
        "conversation_id": 123,
        "workbench_config": canonical.model_dump(mode="json"),
        "workbench_config_version": 2,
        "runtime_metadata": {"existing": True},
        "runtime_metadata_version": 4,
        "knowledge_scope": None,
    }
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=99)))
    apply_plan = MagicMock()
    apply_plan.side_effect = lambda agent_request, *_args: agent_request.__dict__.update(
        {"agent_id": 99, "version_no": 5}
    )
    update_config = MagicMock(
        return_value={"workbench_config_version": 3, "runtime_metadata": {"existing": True}}
    )

    workbench = ModuleType("services.workbench_service")
    workbench.assert_workbench_version = MagicMock()
    workbench.resolve_workbench_config = MagicMock(return_value=(canonical, plan))
    monkeypatch.setitem(sys.modules, "services.workbench_service", workbench)
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        MagicMock(return_value=("user-a", "tenant-a", "en")),
    )
    monkeypatch.setattr(agent_run, "prepend_current_time", lambda query, _timezone: query)
    monkeypatch.setattr(agent_run, "get_conversation_service", MagicMock(return_value=conversation))
    monkeypatch.setattr(agent_run, "apply_workbench_runtime_plan", apply_plan)
    monkeypatch.setattr(agent_run, "update_conversation_workbench_config_service", update_config)
    monkeypatch.setattr(agent_run, "update_conversation_chat_mode_service", MagicMock())
    monkeypatch.setattr(agent_run, "save_messages", MagicMock())
    monkeypatch.setattr(
        agent_run,
        "build_agent_run_context",
        MagicMock(return_value=SimpleNamespace(metadata={}, enable_memory=False)),
    )
    monkeypatch.setattr(agent_run, "agent_monitoring_context", lambda _metadata: nullcontext())

    execution = MagicMock()
    execution.execution_id = "execution-a"
    execution.future.done.return_value = True
    monkeypatch.setattr(agent_run.agent_run_manager, "reserve_agent_capacity", MagicMock(return_value="cap"))
    monkeypatch.setattr(agent_run.agent_run_manager, "reserve_agent_run", MagicMock(return_value="run"))
    monkeypatch.setattr(agent_run.agent_run_manager, "release_agent_run_reservation", MagicMock())
    monkeypatch.setattr(agent_run.runtime_thread_manager, "submit", MagicMock(return_value=execution))
    monkeypatch.setattr(agent_run.runtime_thread_manager, "wait_until_started", AsyncMock())
    monkeypatch.setattr(agent_run.runtime_state_service, "reset_stream_async", AsyncMock())
    monkeypatch.setattr(
        agent_run.streaming_channel_manager,
        "get_or_create_channel",
        AsyncMock(return_value=None),
    )

    async def generate_stream(*_args, **_kwargs):
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr(agent_run, "generate_stream", generate_stream)

    response = await agent_run.run_agent_stream(
        request,
        Request(scope={"type": "http", "headers": []}),
        "Bearer token",
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert workbench.assert_workbench_version.call_count == 2
    workbench.resolve_workbench_config.assert_called_once_with(
        canonical,
        tenant_id="tenant-a",
        is_debug=False,
        user_id="user-a",
    )
    apply_plan.assert_called_once_with(request, canonical, plan, "tenant-a")
    update_config.assert_called_once()
    assert request.__dict__["_workbench_config_version"] == 3
    assert request.__dict__["_runtime_metadata_snapshot"] == {"existing": True}
    assert request.__dict__["_runtime_metadata_version"] == 4
    assert response.headers["x-workbench-config-version"] == "3"
    assert any("workbench_config_resolved" in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_run_agent_stream_rejects_disabled_workbench_entrypoint(monkeypatch):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    workbench = WorkbenchSessionConfig.model_validate(
        {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 7}]}
    )
    request = _request(entrypoint="workbench", workbench=workbench)
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", False)

    with pytest.raises(agent_run.WorkbenchError, match="WORKBENCH_DISABLED"):
        await agent_run.run_agent_stream(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )


@pytest.mark.asyncio
async def test_run_agent_stream_rejects_stored_workbench_when_disabled(monkeypatch):
    from fastapi import Request

    request = _request()
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", False)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        lambda **_kwargs: ("user-a", "tenant-a", "en"),
    )
    monkeypatch.setattr(agent_run, "prepend_current_time", lambda query, _timezone: query)
    monkeypatch.setattr(
        agent_run,
        "get_conversation_service",
        lambda **_kwargs: {"workbench_config": {"schema_version": 3}},
    )

    with pytest.raises(agent_run.WorkbenchError, match="WORKBENCH_DISABLED"):
        await agent_run.run_agent_stream(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )


@pytest.mark.asyncio
async def test_run_agent_stream_rejects_conversation_entrypoint_mismatch(monkeypatch):
    from fastapi import Request

    request = _request(entrypoint="workbench", workbench=None)
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        lambda **_kwargs: ("user-a", "tenant-a", "en"),
    )
    monkeypatch.setattr(agent_run, "prepend_current_time", lambda query, _timezone: query)
    monkeypatch.setattr(
        agent_run,
        "get_conversation_service",
        lambda **_kwargs: {"workbench_config": None},
    )

    with pytest.raises(agent_run.ForbiddenError, match="different chat entrypoint"):
        await agent_run.run_agent_stream(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )


@pytest.mark.asyncio
async def test_run_agent_stream_rejects_stale_metadata_version(monkeypatch):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    workbench = WorkbenchSessionConfig.model_validate(
        {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 7}]}
    )
    request = _request(
        entrypoint="workbench",
        workbench=workbench,
        metadata={"ticket": "NEX-1"},
        expected_metadata_version=2,
    )
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        lambda **_kwargs: ("user-a", "tenant-a", "en"),
    )
    monkeypatch.setattr(agent_run, "prepend_current_time", lambda query, _timezone: query)
    monkeypatch.setattr(
        agent_run,
        "get_conversation_service",
        lambda **_kwargs: {
            "workbench_config": workbench.model_dump(mode="json"),
            "runtime_metadata_version": 3,
        },
    )
    workbench_module = ModuleType("services.workbench_service")
    workbench_module.assert_workbench_version = MagicMock()
    workbench_module.resolve_workbench_config = MagicMock()
    monkeypatch.setitem(sys.modules, "services.workbench_service", workbench_module)

    with pytest.raises(agent_run.AppException) as caught:
        await agent_run.run_agent_stream(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )
    assert caught.value.error_code == agent_run.ErrorCode.CHAT_METADATA_VERSION_CONFLICT
