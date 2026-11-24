# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep runtime time context separate from the captured user query."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, PreparedAgentRun, PreparedEphemeralRun
from infrastructure.agent_model_config import create_model_config_from_record
from management.services.agent import authorization, tool_identity
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls
from nexent.core.agents.contracts.config import AgentConfig
from nexent.monitor import get_agent_monitoring_context
from runtime.agentos import ephemeral, prepared_run

from ..app.test_agentos_prepared_evaluation import model_record
from ..app.test_agentos_prepared_run import ACTOR, runtime
from .model_profile_helpers import stub_resolved_model_catalog
from .test_core_service_slimming import dependency, load_source


@pytest.fixture
def run_context(monkeypatch):
    manager = SimpleNamespace(bind_agent_context=Mock(side_effect=lambda value: value))
    memory = Mock(return_value=SimpleNamespace(user_config=SimpleNamespace(memory_switch=False)))
    dependency(monkeypatch, "infrastructure.trace.bootstrap", monitoring_manager=manager)
    dependency(monkeypatch, "nexent.monitor.local_content", local_capture_enabled=lambda _manager: False)
    dependency(monkeypatch, "management.services.configuration.user.memory", build_memory_context=memory)
    dependency(
        monkeypatch, "management.services.monitor.identity",
        resolve_monitoring_user_email=lambda *_args: "user@example.test",
    )
    module = load_source(
        monkeypatch, "backend/management/services/agent/context.py", "trajectory_user_query_context",
    )
    monkeypatch.setattr(module, "AgentRunMetadata", SimpleNamespace)
    return SimpleNamespace(module=module, manager=manager, memory=memory)


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True], ids=["chat", "debug"])
@pytest.mark.parametrize("query,zone,language,marker", [
    ("计算1到20", "Asia/Shanghai", "zh", "[当前时间:"),
    ("Calculate 1 to 20", "UTC", "en", "[Current time:"),
    ("  原始输入\n", None, "zh", None),
    ("计算1到20", "invalid/zone", "zh", None),
    ("", "Asia/Shanghai", "zh", None),
    ("用户提供的日期\n\n[当前时间: 2026-01-01 00:00:00]", "Asia/Shanghai", "zh", None),
])
async def test_stream_captures_query_before_runtime_time(mocker, runtime, query, zone, language, marker, debug):
    row = model_record(tenant_id=ACTOR.tenant_id)
    model = create_model_config_from_record(row)
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "create_model_config_list", return_value=[model])
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(run, "create_agent_config", return_value=AgentConfig(
        agent_id=7, version_no=0 if debug else 3, name="test", description="", model_name=model.cite_name, tools=[],
    ))
    stub_resolved_model_catalog(mocker, row)
    mocker.patch.object(tool_identity, "resolve_tool_user_context", return_value={})
    request = AgentRequest(agent_id=7, version_no=0 if debug else 3, query=query, is_debug=debug)
    reference = AgentRunReference(run_id="a" * 32, conversation_id=42)
    if debug:
        mocker.patch.object(authorization, "authorize_debug_version", return_value={})
        mocker.patch.object(run_controls, "preflight_turn_controls")
        debug_prepared = await evaluation_snapshot.prepare_debug_snapshot(
            request, ACTOR.user_id, ACTOR.tenant_id, language=language, timezone=zone,
        )
        snapshot = PreparedEphemeralRun.model_validate_json(debug_prepared.payload.model_dump_json())
    else:
        mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
        mocker.patch.object(run_controls, "validate_agent_model_selection")
        mocker.patch.object(run_controls, "preflight_agent_turn_controls")
        prepared = await evaluation_snapshot.prepare_conversation_snapshot(
            request.model_copy(update={"conversation_id": 42}), reference, ACTOR.user_id, ACTOR.tenant_id,
            new_conversation=True, language=language, timezone=zone,
        )
        snapshot = PreparedAgentRun.model_validate_json(prepared.model_dump_json())

    if marker:
        assert snapshot.input.query.startswith(query + "\n\n" + marker)
        assert snapshot.input.user_query == query
    else:
        assert snapshot.input.query == query
        assert "user_query" not in snapshot.input.model_dump()

    if debug:
        manager = mocker.patch.object(ephemeral, "runtime_thread_manager")
        manager.wait_until_started = AsyncMock()
        mocker.patch.object(ephemeral, "agent_run_manager")
        mocker.patch.object(ephemeral, "load_prepared_run", return_value=SimpleNamespace(workspace_run_id=snapshot.run_id))
        response = await ephemeral._open_ephemeral(snapshot, ACTOR)
        metadata = response.metadata
    else:
        seen = []

        async def stream(info, **_opts):
            assert info is runtime.info
            seen.append(get_agent_monitoring_context())
            yield '{"type":"final_answer","content":"answer"}'

        mocker.patch.object(prepared_run, "agent_run", side_effect=stream)
        await prepared_run._run_snapshot(
            snapshot, ACTOR,
            prepared_run.RunIdentity(ACTOR.tenant_id, ACTOR.user_id, 42, reference.run_id), Mock(),
        )
        metadata, = seen
        assert metadata.conversation_id == 42

    assert (metadata.user_id, metadata.tenant_id, metadata.agent_id) == (ACTOR.user_id, ACTOR.tenant_id, 7)
    assert metadata.query == query
    assert metadata.language == language
    assert metadata.is_debug is debug


@pytest.mark.parametrize("options,expected", [
    ({}, "execution query"),
    ({"user_query": None}, "execution query"),
    ({"user_query": "用户输入"}, "用户输入"),
    ({"user_query": ""}, ""),
])
def test_run_context_original_query_and_background_fallback(run_context, options, expected):
    request = SimpleNamespace(
        agent_id=1, conversation_id=123, query="execution query",
        is_debug=False, history=[], minio_files=[],
    )
    result = run_context.module.build_agent_run_context(request, "u", "t", "zh", extra_metadata={}, **options)
    assert result.metadata.query == expected
    assert request.query == "execution query"


def test_run_context_defers_failed_memory_policy_until_bounded_compilation(run_context):
    run_context.memory.side_effect = RuntimeError("controlled preparation failure")
    request = SimpleNamespace(
        agent_id=1, conversation_id=123, query="execution query", is_debug=False,
        history=[], minio_files=[],
    )
    result = run_context.module.build_agent_run_context(
        request, "u", "t", "zh", extra_metadata={}, user_query="用户输入",
    )
    run_context.memory.assert_not_called()
    run_context.manager.bind_agent_context.assert_called_once()
    assert result.metadata.query == "用户输入"
    assert result.metadata.memory_enabled is None
    assert request.query == "execution query"
