# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile and project NL2Skill runs at the Management boundary."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import uuid4

from contracts.agent import NL2SkillRunRequest
from contracts.agentos import PreparedSkillCreatorRun, RunModelBinding, TurnModelGeneration
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.model import WorkbenchGenerationConfig
from infrastructure.agent_model_config import model_record_revision
from management.db.model.repository import get_model_by_model_id, get_model_records
from management.services.agent.agentos_events import iter_sse_frames
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from management.services.agent.runtime_client import forward_skill_creator_run
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.run_budget import _resolve_context_budget, _resolve_input_budget
from management.services.model.run_controls import preflight_turn_controls, validate_selected_record
from management.services.skill.nl2skill import _extract_target_files, _normalize_draft_snapshot, project_creation_events


def prepare_nl2skill_snapshot(
    request: NL2SkillRunRequest, user_id: str, tenant_id: str, language: str,
) -> PreparedSkillCreatorRun:
    preflight_turn_controls(request, tenant_id)
    if request.model_id is not None:
        record = validate_selected_record(get_model_by_model_id(request.model_id, tenant_id))
    else:
        record = tenant_config_manager.get_model_config(MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
        if not record:
            records = get_model_records({"model_type": "llm"}, tenant_id)
            if not records:
                raise ValueError("No LLM model configured for tenant")
            record = records[0]
    values = request.generation_config.model_dump(exclude_unset=True) if request.generation_config else {}
    generation = TurnModelGeneration(settings=WorkbenchGenerationConfig(**values)) if values else None
    input_budget, capacity, resolved = _resolve_input_budget(record)
    context = _resolve_context_budget(
        capacity_snapshot=resolved, tenant_id=tenant_id,
        agent_requested_output_tokens=None, request_requested_output_tokens=None,
    )
    return PreparedSkillCreatorRun(
        mode="nl2skill", run_id=uuid4().hex, language="en" if language == "en" else "zh",
        input=build_evaluation_input(
            request.query, request.minio_files,
            [item for item in request.history or [] if item.role in {"user", "assistant"}], user_id, tenant_id,
        ),
        model=RunModelBinding(
            model_id=record["model_id"], alias=record["display_name"], revision=model_record_revision(record),
            turn_generation=generation,
        ),
        draft=_normalize_draft_snapshot(request.draft_snapshot),
        target_files=_extract_target_files(request.query, request.draft_snapshot),
        input_budget=input_budget, context_window_tokens=(resolved.context_window_tokens if resolved else None) or input_budget,
        capacity_snapshot=capacity, context_budget_snapshot=context.model_dump(mode="json") if context else None,
    )


def create_nl2skill_stream(payload: PreparedSkillCreatorRun, user_id: str, tenant_id: str) -> AsyncIterator[str]:
    """Open the private stream only when the public response starts consuming it."""

    async def observer_events():
        response = await forward_skill_creator_run(payload, user_id, tenant_id)
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
