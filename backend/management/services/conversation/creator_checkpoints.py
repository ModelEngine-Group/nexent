# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Incremental, ordered persistence of creator SSE output."""

import asyncio
import json
import time

from infrastructure.runtime_output import is_runtime_event
from management.db.conversation.repository import checkpoint_creator_message
from nexent.core.concurrency import run_blocking


async def checkpoint_creator_stream(stream, *, message_id, conversation_id, user_id):
    pending = []
    index = 0
    answer = []
    status = "completed"
    last_flush = time.monotonic()

    async def flush(state):
        nonlocal last_flush
        write = asyncio.create_task(
            run_blocking(
                "creator-checkpoint",
                checkpoint_creator_message,
                message_id,
                conversation_id,
                user_id,
                list(pending),
                "".join(answer),
                state,
            )
        )
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            # The database worker can commit after its caller is cancelled.
            # Settle it before the terminal flush to avoid inserting a delta twice.
            await write
            pending.clear()
            last_flush = time.monotonic()
            raise
        pending.clear()
        last_flush = time.monotonic()

    try:
        async for event in stream:
            chunks = []
            for line in event.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict) or not isinstance(
                    chunk.get("type"), str
                ):
                    continue
                chunk["unit_index"] = index
                kind = chunk["type"]
                content = chunk.get("content", "")
                if kind == "nl2a":
                    payload = (
                        json.loads(content)
                        if isinstance(content, str)
                        else dict(content)
                    )
                    payload["card_id"] = f"{message_id}:{index}"
                    content = json.dumps(payload, ensure_ascii=False)
                    chunk["content"] = content
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                if is_runtime_event(chunk) or kind in {
                    "skill_body",
                    "file_content",
                    "agent_new_run",
                    "target_files",
                    "model_attempt_control",
                    "done",
                }:
                    content = json.dumps(chunk, ensure_ascii=False)
                pending.append(
                    {
                        "unit_index": index,
                        "unit_type": kind,
                        "unit_content": content,
                        "tool_call_id": chunk.get("tool_call_id"),
                        "invocation_id": chunk.get("invocation_id"),
                    }
                )
                index += 1
                if kind == "final_answer":
                    answer.append(str(chunk.get("content") or ""))
                if kind == "error":
                    status = "failed"
                if is_runtime_event(chunk) and kind == "run_terminal" and not chunk.get("invocation_id"):
                    outcome = chunk.get("status")
                    if outcome in {"completed", "failed", "stopped"}:
                        status = outcome
                    if outcome == "completed":
                        answer[:] = [str(chunk.get("final_content") or "")]
                chunks.append(chunk)
            # Persist boundaries before publishing; token-only checkpoints are batched.
            if (
                len(pending) >= 64
                or time.monotonic() - last_flush >= 0.25
                or any(
                    chunk["type"] in {"nl2a", "nl2a_state", "error", "done"}
                    for chunk in chunks
                )
            ):
                await flush("streaming")
            for chunk in chunks:
                yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
    except (asyncio.CancelledError, GeneratorExit):
        status = "stopped"
        raise
    except Exception:
        status = "failed"
        pending.append(
            {
                "unit_index": index,
                "unit_type": "error",
                "unit_content": "Creator execution failed.",
            }
        )
        raise
    finally:
        await flush(status)
