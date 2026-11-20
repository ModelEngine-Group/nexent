# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Replay real observer output through current Management SSE and PostgreSQL projection."""

import json
import uuid

from sqlalchemy import select
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
    from management.services.agent import prepared_projection
    from management.services.agent.agentos_events import present_public_resume

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
    values = [("agentos_observer", event) for event in output]
    values.append(("agentos_terminal", {"status": info.attempt_outcome}))
    frames = tuple(f"id: {reference.run_id}:{index}\nevent: {kind}\ndata: {json.dumps(value)}\n\n".encode()
                   for index, (kind, value) in enumerate(values, 1))

    async def resume(request, user_id, tenant_id):
        assert request.run_id == reference.run_id and request.conversation_id == conversation
        assert (user_id, tenant_id) == ("owner", "spike-tenant")
        assert request.after_event_id is None

        async def body():
            for frame in frames:
                yield frame
        return StreamingResponse(body())

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
