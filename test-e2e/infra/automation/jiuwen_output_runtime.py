# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Feed real runtime output through the production stream and isolated PostgreSQL DAL."""

import json
from uuid import uuid4

from starlette.responses import StreamingResponse

from jiuwen_context_runtime import context_database as context_database


async def persist_output(monkeypatch, info, output):
    from contracts.agentos import AgentResume, AgentRunReference
    from contracts.conversation import MessageSource
    from management.db.conversation.repository import (
        create_conversation, create_conversation_message, get_conversation_history,
    )
    from management.services.agent import prepared_projection
    from management.services.agent.agentos_events import present_public_resume

    conversation = create_conversation("Output contract", "owner", agent_id=42)["conversation_id"]
    create_conversation_message({
        "conversation_id": conversation, "message_idx": 0, "role": "user", "content": "Current task",
    }, "owner")
    info.conversation_id, info.user_id = conversation, "owner"
    reference = AgentRunReference(conversation_id=conversation, run_id=uuid4().hex)
    terminal = {"status": info.run_result.status}

    async def resume(request, user_id, tenant_id):
        assert request.run_id == reference.run_id
        assert request.conversation_id == conversation and request.after_event_id is None
        assert (user_id, tenant_id) == ("owner", "spike-tenant")

        async def frames():
            for index, event in enumerate(output, 1):
                yield f"id: {reference.run_id}:{index}\nevent: agentos_observer\ndata: {json.dumps(event)}\n\n"
            yield (f"id: {reference.run_id}:{len(output) + 1}\nevent: agentos_terminal\n"
                   f"data: {json.dumps(terminal)}\n\n")

        return StreamingResponse(frames())

    async def inline(_name, operation, *, lane, owner, **kwargs):
        return operation(**kwargs)

    monkeypatch.setattr(prepared_projection, "run_blocking", inline)

    async def persist():
        result = await prepared_projection.resume_assistant_projection(
            resume, reference, "owner", "spike-tenant", message_index=1, message_source=MessageSource.CHAT,
        )
        assert result.status == terminal["status"] and result.chunks == len(output)
        return True

    request = AgentResume(**reference.model_dump())
    response = await resume(request, "owner", "spike-tenant")
    public = present_public_resume(response, request, "owner", on_terminal=persist, include_journal_controls=False)
    wire = [frame.decode("utf-8") async for frame in public.body_iterator]
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
