# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile the selected model and capacity policy for creator modes."""

from contracts.agent import NL2ModelControlsRequest
from contracts.agentos import RunModelBinding, TurnModelGeneration
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.model import WorkbenchGenerationConfig
from infrastructure.agent_model_config import model_record_revision
from management.db.model.repository import get_model_by_model_id, get_model_records
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.run_budget import _resolve_context_budget, _resolve_input_budget
from management.services.model.run_controls import preflight_turn_controls, validate_selected_record


def prepare_creator_model(request: NL2ModelControlsRequest, tenant_id: str) -> dict:
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
    return dict(
        model=RunModelBinding(
            model_id=record["model_id"], alias=record["display_name"], revision=model_record_revision(record),
            turn_generation=generation,
        ),
        input_budget=input_budget, context_window_tokens=(resolved.context_window_tokens if resolved else None) or input_budget,
        capacity_snapshot=capacity, context_budget_snapshot=context.model_dump(mode="json") if context else None,
    )
