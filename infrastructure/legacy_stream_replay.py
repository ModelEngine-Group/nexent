# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Replay a legacy SSE channel without reading or updating conversation records."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse, StreamingResponse

from contracts.constants.constants import STREAM_STATUS_EVENT

if TYPE_CHECKING:
    from infrastructure.agent_stream_channels import StreamingChannelManager
    from infrastructure.redis.run_state import RuntimeStateService


def replay_legacy_stream(
    conversation_id: int,
    user_id: str,
    resume_from_unit_index: int,
    *,
    channel_manager: StreamingChannelManager,
    state_service: RuntimeStateService,
    is_remote_running: bool,
) -> JSONResponse | StreamingResponse:
    # Agent is still running - subscribe to the channel to receive new chunks
    channel = channel_manager.get_channel(
        conversation_id=conversation_id, user_id=user_id
    )
    last_unit_index = resume_from_unit_index - 1

    def _resume_status_chunk(replay_chunk_count: int) -> str:
        payload = {
            "status": "resumed",
            "last_unit_index": last_unit_index,
            "replay_chunk_count": replay_chunk_count,
        }
        return f"data: {json.dumps(payload)}\n\n"

    def _resume_completed_chunk(status: str = "completed") -> str:
        payload = {
            "status": status,
            "last_unit_index": last_unit_index,
        }
        return f"data: {json.dumps(payload)}\n\n"

    if channel is None:
        if state_service.enabled and is_remote_running:

            async def redis_channel_stream():
                replay_events = (
                    await state_service.read_stream_events_async(
                        user_id=user_id,
                        conversation_id=conversation_id,
                    )
                )
                replay_chunk_count = len(replay_events)

                yield STREAM_STATUS_EVENT
                yield _resume_status_chunk(replay_chunk_count)

                last_event_id = "0-0"
                for event_id, chunk in replay_events:
                    last_event_id = event_id
                    if chunk:
                        yield chunk

                while True:
                    events = (
                        await state_service.wait_for_stream_events_async(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            last_id=last_event_id,
                        )
                    )
                    for event_id, chunk in events:
                        last_event_id = event_id
                        if chunk:
                            yield chunk

                    stream_status = (
                        await state_service.get_stream_status_async(
                            user_id=user_id,
                            conversation_id=conversation_id,
                        )
                    )
                    latest_run_state = (
                        await state_service.get_run_state_async(
                            user_id=user_id,
                            conversation_id=conversation_id,
                        )
                    )
                    if stream_status.get("status") or latest_run_state.get(
                        "status"
                    ) in {
                        "completed",
                        "failed",
                        "stopped",
                    }:
                        break

                terminal_status = (
                    stream_status.get("status")
                    or latest_run_state.get("status")
                    or "completed"
                )
                yield STREAM_STATUS_EVENT
                yield _resume_completed_chunk(terminal_status)

            return StreamingResponse(
                redis_channel_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Stream-Status": "resumed",
                    "X-Last-Unit-Index": str(resume_from_unit_index),
                },
            )

        # No channel exists, agent might be in a different state
        return JSONResponse(
            status_code=200,
            content={
                "status": "streaming",
                "message": "Stream channel not found",
            },
        )

    # Subscribe to the channel and stream chunks to the frontend
    async def channel_stream():
        # Include the current buffer size so frontend knows how many chunks to skip
        replay_chunk_count = channel.history_size if channel else 0

        # Emit status event first with chunk count for skip tracking
        yield STREAM_STATUS_EVENT
        yield _resume_status_chunk(replay_chunk_count)

        # Use subscribe_with_history(0) to replay ALL chunks from the buffer
        # This ensures no chunks are lost even if frontend disconnected during streaming
        # The frontend skips all chunks until replay_chunk_count is reached
        async for chunk in channel.subscribe_with_history(0):
            yield chunk

        # Mark as complete when channel ends
        yield STREAM_STATUS_EVENT
        yield _resume_completed_chunk()

    return StreamingResponse(
        channel_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Stream-Status": "resumed",
            "X-Last-Unit-Index": str(resume_from_unit_index),
        },
    )
