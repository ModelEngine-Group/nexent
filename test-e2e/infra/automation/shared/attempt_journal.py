# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise public SSE and assistant persistence through a controlled AgentOS journal."""

import json
from contextlib import aclosing, asynccontextmanager
from uuid import uuid4

from starlette.responses import StreamingResponse

from contracts.agentos import AgentResume, AgentRunReference
from contracts.conversation import MessageSource
from management.services.agent import prepared_projection
from management.services.agent.agentos_events import iter_sse_frames, present_public_resume


@asynccontextmanager
async def observe_attempt_journal(monkeypatch, events):
    """Mock only the Runtime journal input and the final database write."""
    reference = AgentRunReference(conversation_id=999, run_id=uuid4().hex)
    request = AgentResume(**reference.model_dump())
    journal = []
    writes = []

    def frame(kind, payload):
        journal.append(
            f"id: {request.run_id}:{len(journal) + 1}\nevent: {kind}\n"
            f"data: {json.dumps(payload)}\n\n"
        )
        return journal[-1]

    async def live():
        async with aclosing(events) as source:
            async for event in source:
                yield frame("agentos_observer", event)
        yield frame("agentos_terminal", {"status": "completed"})

    async def resume(cursor, user_id, tenant_id):
        assert (cursor, user_id, tenant_id) == (request, "test-user", "test-tenant")

        async def replay():
            for item in journal:
                yield item

        return StreamingResponse(replay(), media_type="text/event-stream")

    async def persist(label, function, *, lane, owner, **fields):
        assert label == "persist-prepared-assistant-projection"
        assert function is prepared_projection.persist_prepared_assistant_projection
        assert (lane, owner) == ("control-io", "management")
        writes.append(fields)
        return 42

    monkeypatch.setattr(prepared_projection, "run_blocking", persist)

    async def on_terminal():
        projection = await prepared_projection.resume_assistant_projection(
            resume, reference, "test-user", "test-tenant",
            message_index=1, message_source=MessageSource.CHAT,
        )
        assert (projection.assistant_message_id, projection.status, projection.chunks) == (
            42, "completed", len(journal) - 1,
        )
        return True

    response = present_public_resume(
        StreamingResponse(live(), media_type="text/event-stream"),
        request, "test-user", on_terminal=on_terminal, include_journal_controls=False,
    )
    assert response.status_code == 200 and response.media_type == "text/event-stream"

    async def payloads():
        async with aclosing(iter_sse_frames(response)) as stream:
            async for item in stream:
                assert item.startswith(b"data: ")
                yield json.loads(item.removeprefix(b"data: "))

    async with aclosing(payloads()) as stream:
        yield stream, writes


async def capture_attempt_journal(monkeypatch, events):
    async def source():
        for event in events:
            yield event

    async with observe_attempt_journal(monkeypatch, source()) as (stream, writes):
        payloads = [payload async for payload in stream]
    assert len(writes) == 1 and writes[0]["terminal_status"] == "completed"
    return payloads, writes[0]
