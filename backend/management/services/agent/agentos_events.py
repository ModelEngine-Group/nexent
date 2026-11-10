# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SSE framing and public presentation for signed AgentOS output."""

import json
import re
from contextlib import aclosing

from starlette.responses import StreamingResponse

from contracts.agentos import EVENT_ID_PATTERN, AgentResume
from contracts.constants.constants import LANGUAGE, SAFE_AGENT_STREAM_ERROR_MESSAGE
from management.services.agent.artifacts import enrich_file_uploads_with_presigned_urls, is_run_output_object
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


def present_ephemeral_stream(response: StreamingResponse, user_id: str, run_id: str) -> StreamingResponse:
    """Preserve complete observer frames and publish only run-owned file references."""
    if response.status_code != 200:
        return response

    async def events():
        outputs = {}
        async with aclosing(iter_sse_frames(response)) as frames:
            async for frame in frames:
                if not frame.startswith(b"data: "):
                    continue
                try:
                    event = json.loads(frame[6:])
                    if not isinstance(event, dict) or event.get("type") == "skill_artifact":
                        continue
                    if event.get("type") == "file_artifact":
                        for output in _output_artifacts(event.get("content"), user_id, run_id):
                            outputs[output["object_name"]] = output
                        continue
                except (TypeError, ValueError):
                    continue
                yield frame + b"\n\n"

        if outputs:
            files = await run_blocking(
                "agentos-ephemeral-sign-outputs", enrich_file_uploads_with_presigned_urls, list(outputs.values()),
                lane="control-io", owner="management",
            )
            event = {"type": "files", "content": json.dumps({"file_uploads": files}, ensure_ascii=False)}
            yield b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n"

    headers = {name: value for name, value in response.headers.items() if name != "content-length"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)


def present_public_resume(
    response: StreamingResponse, request: AgentResume, user_id: str, *,
    on_terminal=None, created=False, include_journal_controls=True, opening_events=(),
) -> StreamingResponse:
    if response.status_code != 200:
        return response

    async def events():
        error_presented = False
        announce_creation = created
        initial_events = iter(opening_events)
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
                if kind != _OBSERVER_LINE:
                    if kind == b"event: agentos_terminal" and cursor.startswith(f"id: {request.run_id}:".encode()):
                        if on_terminal is not None:
                            await on_terminal()
                            if not error_presented and json.loads(data.removeprefix(b"data: ")).get("status") == "failed":
                                yield _PUBLIC_ERROR + b"\n\n"
                        if not include_journal_controls:
                            continue
                    if not include_journal_controls and cursor == b"event: agentos_error":
                        yield _PUBLIC_ERROR + b"\n\n"
                    else:
                        yield frame + b"\n\n"
                    continue
                cursor_id = cursor.removeprefix(b"id: ").decode("ascii", errors="replace")
                if (not cursor.startswith(b"id: ") or not re.fullmatch(EVENT_ID_PATTERN, cursor_id)
                        or not cursor_id.startswith(f"{request.run_id}:")):
                    # Do not give the client a cursor it cannot safely resume.
                    return
                try:
                    data, is_error = await _present_observer(data, request, user_id)
                except (TypeError, ValueError):
                    data, is_error = _PUBLIC_ERROR, True
                error_presented |= is_error
                yield (cursor + b"\n" if include_journal_controls else b"") + data + b"\n\n"

    excluded_headers = {"content-length"}
    if not include_journal_controls:
        excluded_headers.add("x-agentos-run-id")
    headers = {name: value for name, value in response.headers.items() if name not in excluded_headers}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers, background=response.background)
