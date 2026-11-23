# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SSE framing and public presentation for signed AgentOS output."""

import json
import re
from collections.abc import Sequence
from contextlib import aclosing

from starlette.responses import StreamingResponse

from contracts.agentos import EVENT_ID_PATTERN, REPLAY_COUNT_HEADER, AgentResume
from contracts.constants.constants import LANGUAGE, SAFE_AGENT_STREAM_ERROR_MESSAGE, STREAM_STATUS_EVENT
from contracts.constants.environment import NEXENT_AGENT_CORE
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError
from management.services.agent.artifacts import enrich_file_uploads_with_presigned_urls, is_run_output_object
from management.services.agent.stream import AssistantMessageProjection
from management.services.conversation.nexent_output import NexentOutputAdapter
from nexent.core.concurrency import run_blocking

_OBSERVER_LINE = b"event: agentos_observer"
_PUBLIC_ERROR = b"data: " + json.dumps({"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE}).encode("utf-8")


def active_run_error_response(language: str) -> StreamingResponse:
    message = (
        "当前会话已有智能体任务正在运行，请等待任务完成或先停止任务后再重试。"
        if language == LANGUAGE["ZH"]
        else "An agent run is already active for this conversation. Wait for it to finish or stop it before retrying."
    )

    async def events():
        payload = json.dumps({"type": "error", "content": message}, ensure_ascii=False)
        yield f"data: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive",
        "X-Accel-Buffering": "no", "X-Stream-Status": "conflict",
    })


async def iter_sse_frames(response):
    """Read complete frames even when HTTP chunks split a cursor or UTF-8 payload."""
    async with aclosing(response.body_iterator) as chunks:
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
            while (end := buffer.find(b"\n\n")) != -1:
                frame = bytes(buffer[:end])
                del buffer[:end + 2]
                yield frame


def _output_artifacts(content, user_id, run_id):
    if isinstance(content, str):
        content = json.loads(content)
    raw = content.get("artifacts") if isinstance(content, dict) else None
    if not isinstance(raw, list):
        raise ValueError("Missing AgentOS output artifacts")
    outputs = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("object_name")
        if not is_run_output_object(name, user_id, run_id):
            continue
        file_name = item.get("file_name") or item.get("name")
        if not isinstance(file_name, str) or not file_name or "/" in file_name or "\\" in file_name:
            file_name = name.rsplit("/", 1)[-1]
        entry = {"object_name": name, "file_name": file_name, "status": "success"}
        file_size = item.get("file_size", item.get("file_size_bytes", item.get("size")))
        if type(file_size) is int and file_size >= 0:
            entry["file_size"] = file_size
        if isinstance(item.get("mime_type"), str):
            entry["mime_type"] = item["mime_type"]
        outputs[name] = entry
    return list(outputs.values())


async def _present_observer(data, request, user_id):
    if not data.startswith(b"data: "):
        raise ValueError("Missing AgentOS observer data")
    payload = json.loads(data[6:])
    if not isinstance(payload, dict) or payload.get("type") == "skill_artifact":
        raise ValueError("Unsupported AgentOS observer data")
    if payload.get("type") == "execution_result":
        return None, False
    if payload.get("type") != "file_artifact":
        return data, payload.get("type") == "error"
    artifacts = _output_artifacts(payload.get("content"), user_id, request.run_id)
    if artifacts:
        artifacts = await run_blocking(
            "agentos-public-sign-outputs", enrich_file_uploads_with_presigned_urls, artifacts,
            lane="control-io", owner="management",
        )
    public = {"type": "files", "content": json.dumps({"file_uploads": artifacts}, ensure_ascii=False)}
    return b"data: " + json.dumps(public, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), False


def knowledge_scope_event_content(resolved) -> dict:
    """Present the resolved scope without exposing tool bindings."""
    return {
        "effective": {
            "local": {
                "disabled": resolved.local_disabled,
                "knowledge_ids": resolved.local_knowledge_ids,
                "display_names": resolved.local_display_names,
            },
            "aidp": {
                "disabled": resolved.aidp_disabled,
                "kds_ids": resolved.aidp_kds_ids,
                "display_names": resolved.aidp_display_names,
                "metadata_filter": resolved.aidp_metadata_filter,
            },
        },
        "warnings": resolved.warnings,
    }


def debug_preparation_events(prepared) -> list[dict]:
    """Share the public preparation events for both debug entrypoints."""
    events = []
    if prepared.workbench is not None:
        events.append({"type": "workbench_config_resolved", "content": {
            "config_version": 0, "schema_version": prepared.workbench.schema_version,
            "mode": prepared.workbench.mode,
            "agent_mounts": [mount.model_dump(mode="json") for mount in prepared.workbench.agent_mounts],
        }})
    if prepared.knowledge is not None:
        events.append({"type": "knowledge_scope_resolved", "content": knowledge_scope_event_content(prepared.knowledge)})
    return events


def present_ephemeral_stream(
    response: StreamingResponse, user_id: str, run_id: str, *, opening_events: Sequence[dict] = (),
) -> StreamingResponse:
    """Preserve complete observer frames and publish only run-owned file references."""
    if response.status_code != 200:
        return response

    async def events():
        outputs = {}
        prefix = iter(opening_events)
        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                # Enter the Runtime iterator before emitting so a disconnect also closes upstream.
                for event in prefix:
                    yield _public_sse(event)
                if not frame.startswith(b"data: "):
                    continue
                try:
                    event = json.loads(frame[6:])
                    if not isinstance(event, dict) or event.get("type") in {"skill_artifact", "execution_result"}:
                        continue
                    if event.get("type") == "file_artifact":
                        for output in _output_artifacts(event.get("content"), user_id, run_id):
                            outputs[output["object_name"]] = output
                        continue
                except (TypeError, ValueError):
                    continue
                yield frame + b"\n\n"

        for event in prefix:
            yield _public_sse(event)
        if outputs:
            files = await run_blocking(
                "agentos-ephemeral-sign-outputs", enrich_file_uploads_with_presigned_urls, list(outputs.values()),
                lane="control-io", owner="management",
            )
            event = {"type": "files", "content": json.dumps({"file_uploads": files}, ensure_ascii=False)}
            yield _public_sse(event)

    headers = {name: value for name, value in response.headers.items() if name != "content-length"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)


def _public_sse(event: dict) -> bytes:
    return b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n"


def _event_cursor(cursor, run_id):
    value = cursor.removeprefix(b"id: ").decode("ascii", errors="replace")
    if cursor.startswith(b"id: ") and re.fullmatch(EVENT_ID_PATTERN, value) and value.startswith(f"{run_id}:"):
        return value
    return None


async def _restore_output_prefix(output, request, replay_from_start):
    """Restore renderer state through the acknowledged event without publishing it again."""
    try:
        prefix = await replay_from_start()
    except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError):
        return False
    if prefix.status_code != 200:
        return False
    async with aclosing(iter_sse_frames(prefix)) as frames:
        async for frame in frames:
            if frame.startswith(b":"):
                continue
            cursor, _, body = frame.partition(b"\n")
            event_id = _event_cursor(cursor, request.run_id)
            if event_id is None:
                return False
            kind, _, data = body.partition(b"\n")
            if kind == _OBSERVER_LINE:
                try:
                    payload = json.loads(data.removeprefix(b"data: "))
                    if isinstance(payload, dict):
                        output.push(payload)
                except (TypeError, ValueError):
                    return False
            if event_id == request.after_event_id:
                return True
    return False


def present_legacy_journal(response: StreamingResponse, run_id: str, last_unit: int, replay_count: int) -> StreamingResponse:
    """Adapt a scoped AgentOS replay to the cursorless client's public SSE format."""
    cursor_pattern = re.compile(rb"id: " + run_id.encode("ascii") + rb":[1-9][0-9]*")

    def status_event(status, **fields):
        return STREAM_STATUS_EVENT.encode() + _public_sse({"status": status, "last_unit_index": last_unit, **fields})

    async def events():
        opening = True
        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                if opening:
                    yield status_event("resumed", replay_chunk_count=replay_count)
                    opening = False
                if frame.startswith(b":"):
                    yield frame + b"\n\n"
                    continue
                cursor, _, body = frame.partition(b"\n")
                if not cursor_pattern.fullmatch(cursor) or not body:
                    break
                if body.startswith((b"event: agentos_execution_fact\n", b"event: agentos_execution_summary\n")):
                    continue
                if body.startswith(b"event: agentos_terminal\n"):
                    try:
                        status = json.loads(body.split(b"\n", 1)[1].removeprefix(b"data: ")).get("status")
                    except (ValueError, AttributeError):
                        break
                    if status in ("completed", "failed", "stopped"):
                        yield status_event(status)
                        return
                    break
                yield body + b"\n\n"
        yield _PUBLIC_ERROR + b"\n\n"
        yield status_event("failed")

    internal = {"content-length", "x-agentos-run-id", REPLAY_COUNT_HEADER.lower()}
    headers = {name: value for name, value in response.headers.items() if name.lower() not in internal}
    headers.update({"X-Stream-Status": "resumed", "X-Last-Unit-Index": str(last_unit + 1)})
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)


class _CompleteAnswer:
    """Present live root previews and confirm only the durably completed answer."""

    def __init__(self):
        self.projection = AssistantMessageProjection(persist_units=True)
        self.completion = None

    def observer(self, data):
        _, payload = self.projection.project(data[6:])
        kind = payload.get("type")
        if kind == "model_attempt_control" and payload.get("phase") == "rollback":
            if self.completion and self.completion.get("attempt_id") == payload.get("attempt_id"):
                self.completion = None
        if kind != "final_answer":
            return data
        if payload.get("invocation_id"):
            return None
        if payload.get("answer_phase") != "delta":
            self.completion = payload
            return None
        self.completion = None
        if payload.get("content"):
            return _public_sse({**payload, "type": "model_output_thinking", "answer_preview": True})[:-2]
        return None

    def final_frame(self):
        if self.completion is None:
            return None
        step_id = self.completion.get("step_id")
        units = [
            unit for unit in self.projection.units
            if unit["type"] == "final_answer" and not unit.get("invocation_id")
            and (step_id is None or unit.get("_step_id") == step_id)
        ]
        if step_id is None:
            units = units[-1:]
        content = "".join(
            "".join(unit.get("_content_fragments", [unit["content"]])) for unit in units
        )
        if not content.strip():
            return None
        return _public_sse({
            **self.completion, "answer_phase": "complete", "content": content,
            "unit_index": units[-1]["unit_index"],
        })


def present_public_resume(
    response: StreamingResponse, request: AgentResume, user_id: str, *,
    on_terminal=None, created=False, include_journal_controls=True, opening_events=(), complete_answer=False,
    replay_from_start=None,
) -> StreamingResponse:
    if response.status_code != 200:
        return response

    async def events():
        error_presented = False
        announce_creation = created
        initial_events = iter(opening_events)
        output = NexentOutputAdapter()
        restore_prefix = replay_from_start is not None and request.after_event_id is not None
        answer = _CompleteAnswer() if complete_answer and NEXENT_AGENT_CORE == "smolagents" else None
        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                if announce_creation:
                    # Yield only after entering the upstream iterator so disconnect can close it.
                    payload = {"type": "conversation_created", "content": {"conversation_id": request.conversation_id}}
                    yield b"data: " + json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n\n"
                    announce_creation = False
                for opening_event in initial_events:
                    encoded = json.dumps(opening_event, ensure_ascii=False, separators=(",", ":")).encode()
                    yield b"data: " + encoded + b"\n\n"
                cursor, _, body = frame.partition(b"\n")
                kind, _, data = body.partition(b"\n")
                is_terminal = kind == b"event: agentos_terminal" and _event_cursor(cursor, request.run_id) is not None
                if kind in {b"event: agentos_execution_fact", b"event: agentos_execution_summary"}:
                    continue
                if restore_prefix and (kind == _OBSERVER_LINE or is_terminal):
                    restore_prefix = False
                    if not await _restore_output_prefix(output, request, replay_from_start):
                        yield _PUBLIC_ERROR + b"\n\n"
                        return
                if kind != _OBSERVER_LINE:
                    if is_terminal:
                        status = json.loads(data.removeprefix(b"data: ")).get("status")
                        confirmed = await on_terminal() if on_terminal is not None else None
                        for event in output.close("failed" if confirmed is False else status):
                            if event["type"] == "error":
                                if error_presented:
                                    continue
                                error_presented = True
                            yield _public_sse(event)
                        if on_terminal is not None:
                            if not error_presented and (status == "failed" or (answer and confirmed is False)):
                                yield _PUBLIC_ERROR + b"\n\n"
                            if answer and confirmed is True and status == "completed":
                                final_frame = answer.final_frame()
                                if final_frame is not None:
                                    yield final_frame
                        if not include_journal_controls:
                            continue
                    if not include_journal_controls and cursor == b"event: agentos_error":
                        yield _PUBLIC_ERROR + b"\n\n"
                    else:
                        yield frame + b"\n\n"
                    continue
                if _event_cursor(cursor, request.run_id) is None:
                    # Do not give the client a cursor it cannot safely resume.
                    return
                try:
                    data, is_error = await _present_observer(data, request, user_id)
                except (TypeError, ValueError):
                    data, is_error = _PUBLIC_ERROR, True
                error_presented |= is_error
                if data is None:
                    continue
                if answer:
                    data = answer.observer(data)
                    if data is None:
                        continue
                payload = json.loads(data.removeprefix(b"data: "))
                projected = output.push(payload)
                if not projected:
                    continue
                # A derived group advances the journal cursor only after its last public event.
                for event in projected[:-1]:
                    yield _public_sse(event)
                last = data + b"\n\n" if projected[-1] is payload else _public_sse(projected[-1])
                yield (cursor + b"\n" if include_journal_controls else b"") + last

        if output.root is not None and not output.closed and not error_presented:
            yield _PUBLIC_ERROR + b"\n\n"

    excluded_headers = {"content-length", REPLAY_COUNT_HEADER.lower()}
    if not include_journal_controls:
        excluded_headers.add("x-agentos-run-id")
    headers = {name: value for name, value in response.headers.items() if name not in excluded_headers}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)
