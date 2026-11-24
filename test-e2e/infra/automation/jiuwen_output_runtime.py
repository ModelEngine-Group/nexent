# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Replay real observer output through current Management SSE and PostgreSQL projection."""

import json
import uuid
from types import SimpleNamespace

from sqlalchemy import select
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from jiuwen_context_runtime import context_database as context_database


async def persist_output(monkeypatch, info, output):
    from contracts.agentos import AgentResume, AgentRunReference
    from contracts.conversation import MessageSource
    from infrastructure.rdb.account_record import UserAccount, UserTenant
    from infrastructure.rdb.client import get_db_session
    from management.db.conversation.projection_receipt import ConversationProjectionReceipt
    from management.db.trajectory.models import TrajectoryStatistics
    from management.db.conversation.repository import (
        create_conversation, create_conversation_message, get_conversation_history,
    )
    from management.services.agent import prepared_projection, runtime_client
    from management.services.agent import agentos_events
    from management.services.agent.agentos_events import present_public_resume

    # Match the fixed Management deployment to the actual root runtime under test.
    monkeypatch.setattr(runtime_client, "NEXENT_AGENT_CORE", info.agent_config.agent_core)
    monkeypatch.setattr(agentos_events, "NEXENT_AGENT_CORE", info.agent_config.agent_core)

    # The SDK run has already drained. Control only retained-journal delivery and
    # the I/O scheduler; keep the production parser, public projection and DAL.
    with get_db_session() as session:
        for model in (UserAccount, ConversationProjectionReceipt, TrajectoryStatistics):
            model.__table__.create(session.get_bind(), checkfirst=True)
        if session.scalar(select(UserTenant.user_tenant_id).where(UserTenant.user_id == "owner")) is None:
            session.add(UserTenant(user_id="owner", tenant_id="spike-tenant", created_by="owner"))
    conversation = create_conversation("Output contract", "owner", agent_id=42)["conversation_id"]
    create_conversation_message({"conversation_id": conversation, "message_idx": 0, "role": "user",
                                 "content": "Current task"}, "owner")
    info.conversation_id, info.user_id = conversation, "owner"
    reference = AgentRunReference(conversation_id=conversation, run_id=uuid.uuid4().hex)
    from runtime.agentos.prepared_run import _execution_record

    values = []
    for event in output:
        if event.get("type") == "execution_result":
            key, record = _execution_record(info.observer.execution_history, event)
            assert record is not None
            fact = record.payload()
            for field in ("invocation_id", "tool_call_id", "step_id"):
                if isinstance(event.get(field), str):
                    fact[field] = event[field]
            values.append(("agentos_execution_fact", fact))
            info.observer.execution_history.bind_run(key, reference.run_id, len(values))
        else:
            values.append(("agentos_observer", event))
    values.append(("agentos_terminal", {"status": info.attempt_outcome}))
    frames = tuple(f"id: {reference.run_id}:{index}\nevent: {kind}\ndata: {json.dumps(value)}\n\n".encode()
                   for index, (kind, value) in enumerate(values, 1))

    async def resume(request, user_id, tenant_id):
        assert request.run_id == reference.run_id and request.conversation_id == conversation
        assert (user_id, tenant_id) == ("owner", "spike-tenant")
        after = 0
        if request.after_event_id is not None:
            run_id, index = request.after_event_id.split(":")
            assert run_id == reference.run_id and 0 < int(index) <= len(frames)
            after = int(index)
        closed = False

        def close():
            nonlocal closed
            closed = True

        async def body():
            try:
                for frame in frames[after:]:
                    assert not closed
                    yield frame
            finally:
                close()
        return StreamingResponse(body(), background=BackgroundTask(close))

    async def inline_io(_task, function, *, lane, owner, **kwargs):
        assert lane == "control-io" and owner == "management"
        return function(**kwargs)

    monkeypatch.setattr(prepared_projection, "run_blocking", inline_io)
    projected = await prepared_projection.resume_assistant_projection(
        resume, reference, "owner", "spike-tenant", message_index=1, message_source=MessageSource.CHAT)
    assert projected.status == info.attempt_outcome
    replayed = await prepared_projection.resume_assistant_projection(
        resume, reference, "owner", "spike-tenant", message_index=1, message_source=MessageSource.CHAT)
    assert replayed.assistant_message_id == projected.assistant_message_id
    cursor = AgentResume(**reference.model_dump())

    async def confirm_projection():
        confirmed = await prepared_projection.resume_assistant_projection(
            resume, reference, "owner", "spike-tenant", message_index=1, message_source=MessageSource.CHAT)
        assert confirmed == projected
        return True

    async def public_wire():
        upstream = await resume(cursor, "owner", "spike-tenant")
        public = present_public_resume(upstream, cursor, "owner", on_terminal=confirm_projection,
                                       include_journal_controls=False)
        return [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in public.body_iterator]

    wire = await public_wire()
    assert await public_wire() == wire, "Public journal replay changed observer projection"
    roots = [(index, event) for index, event in enumerate(output, 1) if event.get("type") == "tool"
             and event.get("runtime_mode") == "native_agent" and not event.get("invocation_id")]
    if roots and info.run_result.end_reason != "awaiting_input" and info.attempt_outcome == "completed":
        index, call = roots[0]
        expected = next(event for event in output if event.get("type") == "tool_result"
                        and event.get("local_call_id") == call["local_call_id"])
        monkeypatch.setattr(runtime_client, "_agentos_client", lambda: SimpleNamespace(resume=resume))
        resumed = await runtime_client.forward_conversation_resume(
            cursor.model_copy(update={"after_event_id": f"{reference.run_id}:{index}"}), "owner", "spike-tenant")
        chunks = [chunk async for chunk in resumed.body_iterator]
        public = [json.loads(line[6:]) for chunk in chunks for line in chunk.decode().splitlines()
                  if line.startswith("data: ")]
        assert not any(event.get("type") == "tool" and event.get("local_call_id") == call["local_call_id"]
                       for event in public), "Acknowledged tool call was replayed to the client"
        assert any(event.get("type") == "execution_logs" and event.get("local_call_id") == call["local_call_id"]
                   and event["content"] == expected["result"] for event in public)
        assert sum(event.get("type") == "final_answer" and not event.get("invocation_id")
                   for event in public) == 1
    history = get_conversation_history(conversation, "owner")
    assistant = next(message for message in history["message_records"] if message["role"] == "assistant")
    envelopes = []
    for unit in assistant["units"]:
        try:
            value = json.loads(unit["unit_content"])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("runtime_mode") == "native_agent":
            envelopes.append(value)
    return assistant, envelopes, wire
