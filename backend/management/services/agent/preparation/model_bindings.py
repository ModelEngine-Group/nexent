# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export tenant-owned frozen outlet references and explicit parameter layers."""

from fastapi import HTTPException

from contracts.agentos import RunModelBinding, RunModelOverrides, model_binding_owner
from infrastructure.agent_model_config import create_model_config_from_record, model_record_revision, normalize_model_revision
from infrastructure.rdb.agent_model_overrides import read_agent_model_overrides
from management.db.model.repository import get_model_by_model_id
from nexent.core.model_service.profiles.runtime_parameters import merge_agent_parameters, merge_runtime_parameters


def export_resolved_model(alias, selected, tenant_id, resource, preferences, catalog_versions):
    captured = selected.resolved_profile
    record = get_model_by_model_id(captured.outlet_id, tenant_id)
    if not record or record.get("tenant_id") != tenant_id or record.get("delete_flag") != "N":
        raise ValueError("Model outlet is unavailable")
    revision = model_record_revision(record)
    pinned = [value for value in (catalog_versions or {}).values() if value[0] == captured.outlet_id]
    if pinned and any(normalize_model_revision(value[1]) != revision for value in pinned):
        raise HTTPException(status_code=409, detail={"code": "MODEL_REVISION_MISMATCH"})
    base = create_model_config_from_record(record)
    owner = model_binding_owner(resource, alias)
    if owner is None:
        raise ValueError("Model binding has no Agent owner")
    overrides = read_agent_model_overrides(owner.agent_id, owner.version_no, tenant_id) or {}
    entry = overrides.get(str(captured.outlet_id))
    parameters = (preferences or {}).get(str(captured.outlet_id))
    resolved = base.resolved_profile
    if parameters is not None:
        resolved = merge_runtime_parameters(resolved, entry or {}, parameters)
    elif entry:
        resolved = merge_agent_parameters(resolved, entry)
    if resolved != captured:
        raise ValueError("Model parameters changed during resource preparation")
    default_profile = None
    if alias in {"main_model", "sub_model"} and selected.extra_body == {"logprobs": True}:
        base = base.model_copy(update={"extra_body": {"logprobs": True}})
        default_profile = "logprobs"
    changes = {key: getattr(selected, key) for key in RunModelOverrides.model_fields
               if getattr(selected, key) != getattr(base, key)}
    if selected != base.model_copy(update={"cite_name": alias, "resolved_profile": resolved, **changes}):
        raise ValueError("Unsupported model outlet override")
    return RunModelBinding(
        model_id=captured.outlet_id, alias=alias, revision=revision,
        overrides=RunModelOverrides(**changes) if changes else None,
        agent_parameters=entry or None, conversation_parameters=parameters,
        tenant_default_profile=default_profile,
    )
