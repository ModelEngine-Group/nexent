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
        native_output = NexentOutputAdapter(channel="ephemeral_stream")
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
                for projected in native_output.push(event):
                    yield frame + b"\n\n" if projected is event else _public_sse(projected)

        for projected in native_output.close():
            yield _public_sse(projected)
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
    try:
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
                        if not isinstance(payload, dict):
                            return False
                        output.push(payload)
                    except (TypeError, ValueError):
                        return False
                if event_id == request.after_event_id:
                    return True
                if kind == b"event: agentos_terminal":
                    return False
        return False
    finally:
        await prefix.body_iterator.aclose()
        if prefix.background is not None:
            await prefix.background()


def present_legacy_journal(response: StreamingResponse, run_id: str, last_unit: int, replay_count: int) -> StreamingResponse:
    """Adapt a scoped AgentOS replay to the cursorless client's public SSE format."""
    cursor_pattern = re.compile(rb"id: " + run_id.encode("ascii") + rb":[1-9][0-9]*")

    def status_event(status, **fields):
        return STREAM_STATUS_EVENT.encode() + _public_sse({"status": status, "last_unit_index": last_unit, **fields})

    async def events():
        opening = True
        native_output = NexentOutputAdapter(channel="legacy_replay")
        error_presented = False
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
                        for projected in native_output.close(status):
                            yield _public_sse(projected)
                        yield status_event(native_output.status or status)
                        return
                    break
                if body.startswith(_OBSERVER_LINE + b"\n"):
                    try:
                        projected = _project_observer(body[len(_OBSERVER_LINE) + 1:], native_output)
                    except (TypeError, ValueError):
                        break
                    for data, event in projected:
                        error_presented |= event.get("type") == "error"
                        yield body + b"\n\n" if data == body[len(_OBSERVER_LINE) + 1:] else data + b"\n\n"
                else:
                    yield body + b"\n\n"
        for projected in native_output.close("failed"):
            error_presented |= projected.get("type") == "error"
            yield _public_sse(projected)
        if not error_presented:
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


def _project_observer(data, native_output):
    """Reuse the existing mapper while retaining untouched legacy JSON bytes."""
    if not data.startswith(b"data: "):
        raise ValueError("Missing AgentOS observer data")
    payload = json.loads(data[6:])
    if not isinstance(payload, dict):
        raise ValueError("Invalid AgentOS observer data")
    return [(data if event is payload else _public_sse(event)[:-2], event)
            for event in native_output.push(payload)]


def _public_group(data, cursor=None):
    """A raw cursor acknowledges the complete conversion, including fan-out."""
    return b"".join((cursor + b"\n" if cursor and index == len(data) - 1 else b"") + item + b"\n\n"
                    for index, item in enumerate(data))


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
        answer = _CompleteAnswer() if complete_answer and NEXENT_AGENT_CORE == "smolagents" else None
        native_output = NexentOutputAdapter(channel="journal_stream")
        restore_prefix = replay_from_start is not None and request.after_event_id is not None
        terminal_seen = False

        async def render(projected):
            nonlocal error_presented
            rendered = []
            for data, _ in projected:
                try:
                    data, is_error = await _present_observer(data, request, user_id)
                except (TypeError, ValueError):
                    data, is_error = _PUBLIC_ERROR, True
                error_presented |= is_error
                if data is not None:
                    # Native finality already belongs to the explicit run result.
                    if answer and native_output.root is None:
                        data = answer.observer(data)
                    if data is not None:
                        rendered.append(data)
            return rendered

        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                if announce_creation:
                    yield _public_sse({"type": "conversation_created", "content": {
                        "conversation_id": request.conversation_id}})
                    announce_creation = False
                for opening_event in initial_events:
                    yield _public_sse(opening_event)
                cursor, _, body = frame.partition(b"\n")
                kind, _, data = body.partition(b"\n")
                if kind in {b"event: agentos_execution_fact", b"event: agentos_execution_summary"}:
                    continue
                if restore_prefix and (kind == _OBSERVER_LINE or kind == b"event: agentos_terminal"):
                    restore_prefix = False
                    if not await _restore_output_prefix(native_output, request, replay_from_start):
                        yield _PUBLIC_ERROR + b"\n\n"
                        return
                if kind != _OBSERVER_LINE:
                    if kind == b"event: agentos_terminal" and cursor.startswith(f"id: {request.run_id}:".encode()):
                        try:
                            status = json.loads(data.removeprefix(b"data: ")).get("status")
                        except (TypeError, ValueError, AttributeError):
                            status = None
                        confirmed = await on_terminal() if on_terminal is not None else None
                        terminal_seen = status in {"completed", "failed", "stopped"}
                        close_status = status if terminal_seen and (on_terminal is None or confirmed is True) else "failed"
                        projected = [(_public_sse(event)[:-2], event) for event in native_output.close(close_status)]
                        rendered = await render(projected)
                        if rendered:
                            # The terminal control is the last event in this raw group.
                            yield _public_group(rendered)
                        if on_terminal is not None:
                            if not error_presented and (status == "failed" or (answer and confirmed is False)):
                                error_presented = True
                                yield _PUBLIC_ERROR + b"\n\n"
                            if answer and native_output.root is None and confirmed is True and status == "completed":
                                final_frame = answer.final_frame()
                                if final_frame is not None:
                                    yield final_frame
                        if not include_journal_controls:
                            continue
                    if not include_journal_controls and cursor == b"event: agentos_error":
                        error_presented = True
                        yield _PUBLIC_ERROR + b"\n\n"
                    else:
                        yield frame + b"\n\n"
                    continue
                cursor_id = cursor.removeprefix(b"id: ").decode("ascii", errors="replace")
                if (not cursor.startswith(b"id: ") or not re.fullmatch(EVENT_ID_PATTERN, cursor_id)
                        or not cursor_id.startswith(f"{request.run_id}:")):
                    return
                try:
                    projected = _project_observer(data, native_output)
                except (TypeError, ValueError):
                    projected = [(_PUBLIC_ERROR, {"type": "error"})]
                rendered = await render(projected)
                if rendered:
                    yield _public_group(rendered, cursor if include_journal_controls else None)
        if not terminal_seen and native_output.root is not None:
            projected = [(_public_sse(event)[:-2], event) for event in native_output.close("failed")]
            if not error_presented:
                rendered = await render(projected)
                if rendered:
                    yield _public_group(rendered)

    excluded_headers = {"content-length", REPLAY_COUNT_HEADER.lower()}
    if not include_journal_controls:
        excluded_headers.add("x-agentos-run-id")
    headers = {name: value for name, value in response.headers.items() if name not in excluded_headers}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)
