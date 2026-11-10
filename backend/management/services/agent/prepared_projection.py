# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Replay a signed Runtime journal into Management-owned assistant history."""

import json
from contextlib import aclosing
from dataclasses import dataclass

import httpx

from contracts.agentos import AgentResume, AgentRunReference
from contracts.conversation import MessageSource
from contracts.errors.exceptions import RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.db.conversation.repository import persist_prepared_assistant_projection
from management.services.agent.artifacts import transform_skill_files_to_standard_format
from management.services.agent.persistence import canonicalize_assistant_units
from management.services.agent.stream import AssistantMessageProjection
from nexent.core.concurrency import run_blocking


@dataclass(frozen=True)
class ProjectedRun:
    assistant_message_id: int
    status: str
    chunks: int


async def _frames(response):
    async with aclosing(response.body_iterator) as chunks:
        if response.status_code != 200:
            content = b"".join([chunk async for chunk in chunks])
            raise RuntimeUpstreamError(response.status_code, content, dict(response.headers))
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            while (end := buffer.find(b"\n\n")) != -1:
                frame = bytes(buffer[:end])
                del buffer[:end + 2]
                if frame and not frame.startswith(b":"):
                    yield frame


def _parse_frame(frame: bytes, expected: str):
    try:
        event_id, kind, data = frame.decode("utf-8").split("\n")
        if event_id != f"id: {expected}" or not kind.startswith("event: ") or not data.startswith("data: "):
            raise ValueError("Unexpected AgentOS event")
        data = data.removeprefix("data: ")
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("Expected an AgentOS event object")
        return kind.removeprefix("event: "), data, payload
    except (TypeError, ValueError) as exc:
        raise RuntimeServiceUnavailableError("Invalid or missing AgentOS projection event") from exc


async def _consume_projection(resume, reference, user_id, tenant_id, projection, files):
    cursor = None
    index = 0
    for _ in range(2):
        response = await resume(AgentResume(**reference.model_dump(), after_event_id=cursor), user_id, tenant_id)
        try:
            async with aclosing(_frames(response)) as frames:
                async for frame in frames:
                    index += 1
                    next_id = f"{reference.run_id}:{index}"
                    kind, data, payload = _parse_frame(frame, next_id)
                    if kind == "agentos_terminal" and payload.get("status") in ("completed", "failed", "stopped"):
                        return payload["status"], index - 1
                    if kind != "agentos_observer":
                        raise RuntimeServiceUnavailableError("Unexpected AgentOS projection event")
                    _project_event(projection, files, data, payload)
                    cursor = next_id
        except httpx.TransportError:
            # The last full frame is safe to retain; an incomplete frame is read again.
            continue
    raise RuntimeServiceUnavailableError("AgentOS journal ended before its terminal event")


def _project_event(projection, files, data, payload):
    if payload.get("type") == "skill_artifact":
        raise RuntimeServiceUnavailableError("Runtime must upload skill artifacts before projection")
    if payload.get("type") != "file_artifact":
        projection.project(data)
        return

    content = payload.get("content")
    try:
        content = json.loads(content) if isinstance(content, str) else content
        for artifact in content["artifacts"]:
            name = artifact["object_name"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Missing artifact object reference")
            # Replays must compare the stable object metadata, without expiring signatures.
            files[name] = {key: value for key, value in artifact.items() if key != "presigned_url"}
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeServiceUnavailableError("Invalid Runtime file artifact") from exc


async def resume_assistant_projection(
    resume, reference: AgentRunReference, user_id: str, tenant_id: str, *,
    message_index: int, message_source: MessageSource,
) -> ProjectedRun:
    """Commit only a complete projection and let duplicate replays reuse its receipt."""
    projection = AssistantMessageProjection(persist_units=True)
    files = {}
    status, chunks = await _consume_projection(resume, reference, user_id, tenant_id, projection, files)
    answer, _ = canonicalize_assistant_units(projection.units)
    message_id = await run_blocking(
        "persist-prepared-assistant-projection", persist_prepared_assistant_projection,
        lane="control-io", owner="management", projection_run_id=reference.run_id,
        conversation_id=reference.conversation_id, message_index=message_index, message_source=message_source,
        user_id=user_id, tenant_id=tenant_id, message_content=answer, terminal_status=status,
        message_units=projection.units, search_records=projection.search_records, image_urls=projection.image_urls,
        skill_files=transform_skill_files_to_standard_format(list(files.values())),
        automation_proposals=projection.automation_proposals,
    )
    return ProjectedRun(message_id, status, chunks)
