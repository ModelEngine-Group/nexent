# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creation runs bind saved identities without leaking context to stream consumers."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest, SystemAgentRef
from contracts.constants.environment import APP_VERSION
from management.services.conversation import creation_history
from management.services.conversation import creator_execution as execution
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)

EVENT = 'data: {"type":"string","content":"answer"}\n\n'


@pytest.fixture
def creator(mocker):
    mocker.patch.object(
        execution.system_agent_provider, "get_creator_ref",
        side_effect=lambda tenant, key: SystemAgentRef("shared", key, 77, 0),
    )
    mocker.patch.object(execution, "authorize_target", side_effect=lambda target, *_: target)
    mocker.patch.object(creation_history, "create_new_conversation", return_value={"conversation_id": 9})
    save = mocker.patch.object(creation_history, "save_message", side_effect=range(10, 50))
    mocker.patch.object(creation_history, "save_message_unit")
    history = {
        "agent_id": 77, "target": {"type": "agent", "id": 201},
        "message_records": [
            {"role": "user", "message_id": 10, "message_index": 0,
             "message_content": "build", "minio_files": None},
            {"role": "assistant", "message_id": 11, "message_index": 1},
        ],
    }
    mocker.patch.object(execution, "get_conversation_history", return_value=history)
    mocker.patch.object(creation_history, "get_conversation_history", return_value=history)
    mocker.patch(
        "management.services.conversation.model_preferences.read_model_preferences",
        return_value={"model_parameter_preferences": {}, "selected_model_id": None},
    )
    return save, history


class RuntimeStream:
    def __init__(self, error=None):
        self.contexts = []
        self.closed = []
        self.count = 0
        self.error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.contexts.append(get_agent_monitoring_context())
        self.count += 1
        await asyncio.sleep(0)
        if self.error:
            raise self.error
        if self.count == 1:
            return EVENT
        raise StopAsyncIteration

    async def aclose(self):
        self.closed.append(get_agent_monitoring_context())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("workbench", [False, True])
@pytest.mark.parametrize("turn,source_id,user_index", [("new", "10", 0), ("followup", "12", 2), ("retry", "10", None)])
async def test_saved_creation_identity_and_receipt_reach_runtime(
    creator, kind, workbench, turn, source_id, user_index,
):
    save, history = creator
    if turn == "followup":
        save.side_effect = [12, 13]
    history["target"]["type"] = kind
    config = {"schema_version": 4, "mode": f"{kind}_create", "agent_mounts": [], "skill_mounts": []}
    request = (NL2AgentRunRequest if kind == "agent" else NL2SkillRunRequest)(
        query="build", target={"type": kind, "id": 201},
        conversation_id=None if turn == "new" else 9,
        retry_user_message_id=10 if turn == "retry" else None,
        workbench_config=config if workbench else None,
    )
    raw = RuntimeStream()
    factory = AsyncMock(return_value=raw)
    outer = AgentRunMetadata(tenant_id="other", user_id="other", conversation_id=888, agent_id=999)
    with agent_monitoring_context(outer):
        stream, conversation_id = await execution.start_creation_turn(
            request, kind=kind, tenant_id="tenant", user_id="owner", stream_factory=factory,
        )
        assert get_agent_monitoring_context() is outer
        assert raw.contexts == []
        assert [event async for event in stream] == [EVENT]
        assert get_agent_monitoring_context() is outer
    metadata = raw.contexts[0]
    assert metadata is not outer
    assert (metadata.tenant_id, metadata.user_id, metadata.conversation_id, metadata.agent_id) == (
        "tenant", "owner", conversation_id, 77,
    )
    assert conversation_id == 9 and metadata.query == "build"
    assert metadata.extra_metadata["trajectory_source_message_id"] == source_id
    assert metadata.extra_metadata["app_version"] == APP_VERSION
    assert metadata.extra_metadata["core_type"] == "smolagents"
    assert len(raw.closed) == 1 and raw.closed[0] is metadata
    assert all(context is metadata for context in raw.contexts)
    if user_index is None:
        assert [call.args[0].role for call in save.call_args_list] == ["assistant"]
    else:
        assert [call.args[0].role for call in save.call_args_list] == ["user", "assistant"]
        assert save.call_args_list[0].args[0].message_idx == user_index
    effective, ref = factory.call_args.args
    assert ref.agent_id == 77 and effective.target.id == 201
    if kind == "agent":
        assert effective.agent_id == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("runtime failed"), asyncio.CancelledError()])
async def test_runtime_failure_and_cancellation_restore_context_and_close(creator, failure):
    save, _ = creator
    raw = RuntimeStream(failure)
    stream, _ = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
        user_id="owner", stream_factory=AsyncMock(return_value=raw),
    )
    before = get_agent_monitoring_context()
    with pytest.raises(type(failure)):
        await anext(stream)
    assert get_agent_monitoring_context() is before
    assert len(raw.closed) == 1
    assert raw.closed[0].conversation_id == 9
    assert save.call_args.kwargs["status"] == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_explicit_close_releases_once_even_before_first_event(creator, started):
    save, _ = creator
    raw = RuntimeStream()
    stream, _ = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
        user_id="owner", stream_factory=AsyncMock(return_value=raw),
    )
    before = get_agent_monitoring_context()
    if started:
        assert await anext(stream) == EVENT
        assert get_agent_monitoring_context() is before
    await stream.aclose()
    await stream.aclose()
    assert get_agent_monitoring_context() is before
    assert len(raw.closed) == 1
    assert raw.closed[0].conversation_id == 9
    if started:
        assert save.call_args.kwargs["status"] == "stopped"
    else:
        assert save.call_count == 1
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_save_failure_closes_unstarted_runtime_without_capture(creator, mocker):
    save, _ = creator
    save.side_effect = RuntimeError("save failed")
    raw = RuntimeStream()
    before = get_agent_monitoring_context()
    with pytest.raises(RuntimeError, match="save failed"):
        await execution.start_creation_turn(
            NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
            user_id="owner", stream_factory=AsyncMock(return_value=raw),
        )
    assert raw.contexts == [] and raw.closed == [before]
    assert get_agent_monitoring_context() is before


@pytest.mark.asyncio
async def test_interleaved_streams_do_not_share_identity(creator):
    async def consume(tenant, user):
        raw = RuntimeStream()
        stream, _ = await execution.start_creation_turn(
            NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id=tenant,
            user_id=user, stream_factory=AsyncMock(return_value=raw),
        )
        before = get_agent_monitoring_context()
        async for _ in stream:
            assert get_agent_monitoring_context() is before
            await asyncio.sleep(0)
        assert all((item.tenant_id, item.user_id) == (tenant, user) for item in raw.contexts + raw.closed)
    await asyncio.gather(consume("tenant-a", "user-a"), consume("tenant-b", "user-b"))


@pytest.mark.asyncio
async def test_invalid_retry_never_runs_or_claims_saved_message(creator):
    save, _ = creator
    raw = RuntimeStream()
    with pytest.raises(ValueError, match="Invalid creation retry"):
        await execution.start_creation_turn(
            NL2AgentRunRequest(query="changed", agent_id=201, conversation_id=9, retry_user_message_id=10),
            kind="agent", tenant_id="tenant", user_id="owner", stream_factory=AsyncMock(return_value=raw),
        )
    assert raw.contexts == [] and len(raw.closed) == 1
    save.assert_not_called()


@pytest.mark.asyncio
async def test_response_iterator_close_releases_runtime(creator):
    raw = RuntimeStream()
    stream, _ = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
        user_id="owner", stream_factory=AsyncMock(return_value=raw),
    )
    iterator = aiter(stream)
    before = get_agent_monitoring_context()
    assert await anext(iterator) == EVENT
    assert get_agent_monitoring_context() is before
    await iterator.aclose()
    assert len(raw.closed) == 1 and get_agent_monitoring_context() is before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_id", [None, True, 0, -1, 2147483648, "10"])
async def test_invalid_saved_message_id_cannot_claim_completeness(creator, invalid_id):
    save, _ = creator
    save.side_effect = [invalid_id, 11]
    raw = RuntimeStream()
    stream, _ = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
        user_id="owner", stream_factory=AsyncMock(return_value=raw),
    )
    assert [item async for item in stream] == [EVENT]
    assert "trajectory_source_message_id" not in raw.contexts[0].extra_metadata


@pytest.mark.asyncio
async def test_managed_worker_receives_creation_context_for_file_capture(creator, tmp_path):
    import json

    from infrastructure.observability.trajectory_processor import (
        LocalTrajectoryProcessor,
    )
    from infrastructure.observability.trajectory_store import TrajectoryFileStore
    from nexent.core.concurrency import (
        LanePolicy,
        ManagedTaskSpec,
        ManagedThreadSpec,
        ThreadManager,
    )
    from opentelemetry.sdk.trace import TracerProvider

    TrajectoryFileStore.provision(tmp_path)
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    processor = LocalTrajectoryProcessor(store, get_agent_monitoring_context)
    manager = ThreadManager("creator-capture-ut", {
        "agent-run": LanePolicy("agent-run", 1, 1),
        "background-service": LanePolicy("background-service", 1, 0),
    })
    manager.start()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    processor.start(manager, ManagedThreadSpec("trajectory-writer", "creator-ut", close_hook=processor.request_stop))
    tracer = provider.get_tracer("creator-ut")
    seen = []

    def worker():
        seen.append(get_agent_monitoring_context())
        with tracer.start_as_current_span("agent.run") as root:
            root.set_attribute("nexent.business_status", "completed")
            with tracer.start_as_current_span("model", attributes={"openinference.span.kind": "LLM"}) as model:
                model.set_attribute("output.value", "created")

    async def raw():
        task = manager.submit("agent-run", ManagedTaskSpec("creator-run", "creator-ut"), worker)
        await asyncio.wrap_future(task.future)
        yield EVENT

    try:
        stream, _ = await execution.start_creation_turn(
            NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
            user_id="owner", stream_factory=AsyncMock(return_value=raw()),
        )
        assert [item async for item in stream] == [EVENT]
        assert (seen[0].tenant_id, seen[0].user_id, seen[0].agent_id, seen[0].conversation_id) == (
            "tenant", "owner", 77, 9,
        )
        assert processor.force_flush(3000)
        path = next(tmp_path.rglob("*.otlp.jsonl"))
        assert path.parent.parts[-4:] == ("tenant", "owner", "77", "9")
        spans = [span for line in path.read_text().splitlines()
                 for resource in json.loads(line)["resourceSpans"] for scope in resource["scopeSpans"]
                 for span in scope["spans"]]
        root = next(span for span in spans if span["name"] == "agent.run")
        attributes = {item["key"]: next(iter(item["value"].values())) for item in root["attributes"]}
        assert attributes["nexent.source_message_id"] == "10"
        assert any(span["name"] == "model" for span in spans)
    finally:
        processor.shutdown()
        provider.shutdown()
        await manager.shutdown(timeout=3)
        assert manager.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_cancel_during_pending_runtime_read_restores_consumer_context(creator):
    entered = asyncio.Event()
    closed = []

    async def raw():
        try:
            entered.set()
            await asyncio.Event().wait()
            yield EVENT
        finally:
            closed.append(get_agent_monitoring_context())

    stream, _ = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", agent_id=201), kind="agent", tenant_id="tenant",
        user_id="owner", stream_factory=AsyncMock(return_value=raw()),
    )
    outer = AgentRunMetadata(tenant_id="consumer", user_id="consumer")

    async def consume():
        with agent_monitoring_context(outer):
            try:
                await anext(stream)
            finally:
                assert get_agent_monitoring_context() is outer

    task = asyncio.create_task(consume())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 1 and closed[0].conversation_id == 9
    await stream.aclose()
    assert len(closed) == 1
