"""Feed real runtime output through the production stream and isolated PostgreSQL DAL."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jiuwen_context_runtime import context_database


async def persist_output(monkeypatch, info, output):
    from consts.model import AgentRequest, HistoryItem
    from database.conversation_db import create_conversation, create_conversation_message, get_conversation_history
    from management.services.agent import execution as application

    conversation = create_conversation("Output contract", "owner", agent_id=42)["conversation_id"]
    create_conversation_message({"conversation_id":conversation,"message_idx":0,"role":"user",
                                 "content":"Current task"}, "owner")
    info.conversation_id, info.user_id = conversation, "owner"
    request = AgentRequest(agent_id=42, conversation_id=conversation, query="Current task", is_debug=False,
                           history=[HistoryItem(role="user",content="Current task")])

    async def source(*args, **kwargs):
        for event in output:
            yield json.dumps(event)

    class InlinePersistence:
        async def run(self, lane, spec, function, *args, **kwargs):
            return function(*args, **kwargs)

    # Runtime execution has already drained its own manager. This boundary controls only
    # transport delivery and bookkeeping, retaining the production stream and actual DAL.
    monkeypatch.setattr(application,"agent_run",source)
    monkeypatch.setattr(application,"runtime_thread_manager",InlinePersistence())
    monkeypatch.setattr(application,"_poll_runtime_cancel_signal",AsyncMock())
    monkeypatch.setattr(application,"_unregister_agent_run_after_execution",lambda *a,**k:None)
    monkeypatch.setattr(application,"_cleanup_channel_later",AsyncMock())
    monkeypatch.setattr(application.streaming_channel_manager,"complete_channel",AsyncMock())
    channel = SimpleNamespace(publish=AsyncMock())
    wire = [chunk async for chunk in application._stream_agent_chunks(request,"owner","spike-tenant",info,None,
                                                                    channel=channel)]
    await asyncio.sleep(0)
    history = get_conversation_history(conversation,"owner")
    assistant = next(m for m in history["message_records"] if m["role"]=="assistant")
    envelopes=[]
    for unit in assistant["units"]:
        try: value=json.loads(unit["unit_content"])
        except (TypeError,ValueError):continue
        if isinstance(value,dict) and value.get("runtime_mode")=="native_agent":envelopes.append(value)
    return assistant,envelopes,wire
