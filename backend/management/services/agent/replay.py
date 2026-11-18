# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compact, append-only rendering checkpoints independent of the token tail."""

import json
from typing import Any


_TEXT_DELTAS = frozenset({
    "model_output_code", "model_output_thinking", "model_output_deep_thinking", "final_answer",
})


def encode_event(payload: dict[str, Any]) -> str:
    return payload["_raw"] if "_raw" in payload else f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def replay_after(entries: list[dict[str, Any]], cursor: tuple[int, int] = (0, 0)):
    """Read an immutable prefix plus the suffix of a previously partial text unit."""
    count, offset = cursor
    if count > len(entries):
        raise ValueError("Replay checkpoint belongs to another generation")
    chunks = []
    if count:
        previous = entries[count - 1]
        content = previous.get("content")
        if isinstance(content, str) and len(content) > offset:
            chunks.append(encode_event({**previous, "content": content[offset:]}))
    chunks.extend(encode_event(entry) for entry in entries[count:])
    last_content = entries[-1].get("content", "") if entries else ""
    return chunks, (len(entries), len(last_content) if isinstance(last_content, str) else 0)


class CompactReplay:
    """Keep event boundaries; coalesce only adjacent deltas of the same unit."""

    def __init__(self):
        self.entries: list[dict[str, Any]] = []

    def append(self, chunk: str) -> dict[str, Any]:
        try:
            payload = json.loads(chunk.removeprefix("data: ").strip())
            if not isinstance(payload, dict):
                raise ValueError("Invalid event")
        except (ValueError, TypeError):
            payload = {"_raw": chunk}
        previous = self.entries[-1] if self.entries else None
        merge = bool(
            previous is not None
            and payload.get("type") in _TEXT_DELTAS
            and payload.get("answer_phase") != "complete"
            and isinstance(payload.get("content"), str)
            and isinstance(previous.get("content"), str)
            and {k: v for k, v in payload.items() if k != "content"}
            == {k: v for k, v in previous.items() if k != "content"}
        )
        if merge:
            self.entries[-1] = {**previous, "content": previous["content"] + payload["content"]}
        else:
            self.entries.append(dict(payload))
        return {"slot": len(self.entries) - 1, "append": merge, "payload": payload}

    def read_after(self, cursor: tuple[int, int] = (0, 0)):
        return replay_after(self.entries, cursor)


async def subscribe_shared_checkpoint(service, user_id, conversation_id, initial):
    """Use compact suffixes after waking; a trimmed Redis tail is only a wakeup."""
    checkpoint = initial
    generation = checkpoint["generation"]
    position = (0, 0)
    while True:
        if checkpoint["generation"] != generation:
            yield f'data: {json.dumps({"status": "stopped"})}\n\n'
            return
        chunks, position = replay_after(checkpoint["entries"], position)
        for chunk in chunks:
            yield chunk
        stream_status = await service.get_stream_status_async(user_id, conversation_id)
        run = await service.get_run_state_async(user_id, conversation_id)
        if run.get("generation") and run["generation"] != generation:
            yield f'data: {json.dumps({"status": "stopped"})}\n\n'
            return
        outcome = stream_status.get("status") or run.get("status")
        if outcome in {"completed", "failed", "stopped"}:
            # Terminal status can commit after our read. Drain its last events.
            final = await service.read_replay_checkpoint_async(user_id, conversation_id)
            if final and final["generation"] == generation:
                chunks, _ = replay_after(final["entries"], position)
                for chunk in chunks:
                    yield chunk
            yield f'data: {json.dumps({"status": outcome})}\n\n'
            return
        await service.wait_for_stream_events_async(user_id, conversation_id, checkpoint["cursor"])
        newer = await service.read_replay_checkpoint_async(user_id, conversation_id)
        if newer is None:
            raise RuntimeError("Execution replay checkpoint is no longer available")
        checkpoint = newer
