# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile and project NL2Skill runs at the Management boundary."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import uuid4

from contracts.agent import NL2SkillRunRequest
from contracts.agentos import PreparedSkillCreatorRun
from management.services.agent.agentos_events import iter_sse_frames
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from management.services.agent.runtime_client import forward_creator_run
from management.services.model.creator_snapshot import prepare_creator_model
from management.services.skill.nl2skill import _extract_target_files, _normalize_draft_snapshot, project_creation_events


def prepare_nl2skill_snapshot(
    request: NL2SkillRunRequest, user_id: str, tenant_id: str, language: str,
) -> PreparedSkillCreatorRun:
    model_scope = prepare_creator_model(request, tenant_id)
    return PreparedSkillCreatorRun(
        mode="nl2skill", run_id=uuid4().hex, language="en" if language == "en" else "zh",
        input=build_evaluation_input(
            request.query, request.minio_files,
            [item for item in request.history or [] if item.role in {"user", "assistant"}], user_id, tenant_id,
        ),
        draft=_normalize_draft_snapshot(request.draft_snapshot),
        target_files=_extract_target_files(request.query, request.draft_snapshot),
        **model_scope,
    )


def create_nl2skill_stream(payload: PreparedSkillCreatorRun, user_id: str, tenant_id: str) -> AsyncIterator[str]:
    """Open the private stream only when the public response starts consuming it."""

    async def observer_events():
        response = await forward_creator_run(payload, user_id, tenant_id)
        async with aclosing(iter_sse_frames(response)) as frames:
            if response.status_code != 200:
                # Enter the upstream iterator so its finally block closes the HTTP connection.
                await anext(frames, None)
                raise RuntimeError("NL2Skill execution was rejected by Runtime")
            async for frame in frames:
                if frame.startswith(b"event: agentos_execution_error\ndata: "):
                    yield {"type": "agentos_execution_error", "payload": frame.split(b"\n", 1)[1][6:].decode()}
                    return
                if frame == b"event: agentos_execution_complete\ndata: {}":
                    return
                if frame.startswith(b"data: "):
                    yield frame[6:].decode()
            raise RuntimeError("NL2Skill stream ended before the Runtime terminal")

    return project_creation_events(observer_events(), payload.target_files)
