# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compact, append-only rendering checkpoints independent of the token tail."""

import json
import re
from typing import Any


_TEXT_DELTAS = frozenset({
    "model_output_code", "model_output_thinking", "model_output_deep_thinking", "final_answer",
})
_EXECUTION_CURSOR = re.compile(r"(execution:[1-9][0-9]{0,9}):(0|[1-9][0-9]{0,14}):(0|[1-9][0-9]{0,14})")


def encode_event(payload: dict[str, Any]) -> str:
    return payload["_raw"] if "_raw" in payload else f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def parse_execution_cursor(value: str) -> tuple[str, tuple[int, int]]:
    match = _EXECUTION_CURSOR.fullmatch(value)
    if match is None:
        raise ValueError("Invalid execution replay cursor")
    generation, count, offset = match.groups()
    return generation, (int(count), int(offset))


def _text_extent(payload: dict[str, Any]) -> int:
    content = payload.get("content")
    return len(content) if isinstance(content, str) else 0


def validate_replay_position(entries: list[dict[str, Any]], cursor: tuple[int, int]) -> None:
    count, offset = cursor
    if count > len(entries):
        raise ValueError("Replay cursor belongs to another generation or extends past the retained checkpoint")
    if count < 0 or offset < 0 or (count == 0 and offset != 0):
        raise ValueError("Replay cursor is outside the retained checkpoint")
    if count:
        entry = entries[count - 1]
        extent = _text_extent(entry)
        if offset > extent or (offset < extent and (
            entry.get("type") not in _TEXT_DELTAS or entry.get("answer_phase") == "complete"
        )):
            raise ValueError("Replay cursor is outside the retained event")


def replay_after(entries: list[dict[str, Any]], cursor: tuple[int, int] = (0, 0), *, wire_generation=None):
    """Read an immutable prefix plus the suffix of a previously partial text unit."""
    validate_replay_position(entries, cursor)
    count, offset = cursor

    def frame(payload, index, extent):
        encoded = encode_event(payload)
        if wire_generation is not None and "_raw" not in payload:
            return f"id: {wire_generation}:{index}:{extent}\n{encoded}"
        return encoded

    chunks = []
    if count:
        previous = entries[count - 1]
        content = previous.get("content")
        if isinstance(content, str) and len(content) > offset:
            chunks.append(frame({**previous, "content": content[offset:]}, count, len(content)))
    chunks.extend(frame(entry, index, _text_extent(entry)) for index, entry in enumerate(entries[count:], count + 1))
    return chunks, (len(entries), _text_extent(entries[-1]) if entries else 0)


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

    def read_after(self, cursor: tuple[int, int] = (0, 0), *, wire_generation=None):
        return replay_after(self.entries, cursor, wire_generation=wire_generation)


class ExecutionReplayUnavailable(RuntimeError):
    """The selected execution no longer has a contiguous shared replay."""


async def follow_execution_replay(
    service, user_id, identifier, execution_id, initial, *, is_active, position=(0, 0), include_event_ids=False,
):
    """Read only the owned generation and finish after emitting its atomic terminal snapshot."""
    snapshot = initial
    generation = initial["generation"]
    redis_cursor = "0-0"
    while True:
        if snapshot is None or snapshot["generation"] != generation:
            raise ExecutionReplayUnavailable("Execution replay generation is no longer available")
        if snapshot.get("incomplete"):
            raise ExecutionReplayUnavailable("Execution replay checkpoint is incomplete")
        checkpoint = snapshot["checkpoint"]
        if checkpoint is not None:
            try:
                chunks, position = replay_after(
                    checkpoint["entries"], position, wire_generation=generation if include_event_ids else None,
                )
            except ValueError as exc:
                raise ExecutionReplayUnavailable("Execution replay checkpoint was replaced") from exc
            redis_cursor = checkpoint["cursor"]
            for chunk in chunks:
                yield chunk, None
        elif position != (0, 0):
            raise ExecutionReplayUnavailable("Execution replay checkpoint expired")
        outcome = snapshot["terminal_status"]
        if outcome is not None:
            yield None, outcome
            return
        if not await is_active():
            snapshot = await service.read_execution_stream_async(user_id, identifier, execution_id)
            if not snapshot or not snapshot["terminal_status"]:
                raise ExecutionReplayUnavailable("Terminal execution has no complete replay")
            continue
        await service.wait_for_stream_events_async(user_id, identifier, redis_cursor)
        snapshot = await service.read_execution_stream_async(user_id, identifier, execution_id)


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
