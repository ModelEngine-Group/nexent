# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore signed parameter layers against Runtime's own outlet and Agent reads."""

from fastapi import HTTPException

from contracts.agentos import model_binding_owner
from infrastructure.rdb.agent_model_overrides import read_agent_model_overrides
from nexent.core.model_service.profiles.runtime_parameters import merge_agent_parameters, merge_runtime_parameters


def materialize_profile_parameters(model, binding, actor, resource):
    owner = model_binding_owner(resource, binding.alias)
    if owner is None and resource is not None:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})
    current = (read_agent_model_overrides(owner.agent_id, owner.version_no, actor.tenant_id) or {}) if owner else {}
    entry = current.get(str(binding.model_id)) or None
    if entry != binding.agent_parameters:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_MODEL_PARAMETERS_REVISION_MISMATCH"})
    profile = model.resolved_profile
    if binding.conversation_parameters is not None:
        profile = merge_runtime_parameters(profile, entry or {}, binding.conversation_parameters)
    elif entry:
        profile = merge_agent_parameters(profile, entry)
    return model.model_copy(update={"resolved_profile": profile})
