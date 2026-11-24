# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist Runtime model configuration with tenant and revision checks."""

from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError
from nexent.core.model_service.profiles.configuration import apply_outlet_patch, reselect_outlet_profile, _patch_credentials
from nexent.core.model_service.registry import model_service_references

def update_model_outlet(model_id, request, user_id, tenant_id):
    """Update a frozen outlet with CAS; preserve omitted credentials and fields."""
    from infrastructure.rdb.model_records import get_models_by_display_name, get_model_by_model_id
    from infrastructure.rdb.outlets import get_resolved_model_record, update_resolved_model_record, has_model_outlet_credential

    refs = model_service_references()
    current = get_resolved_model_record(model_id, tenant_id, registered_references=refs)
    if current is None:
        raise LookupError("MODEL_OUTLET_NOT_FOUND")
    if current.identity.model_type != "llm":
        raise ModelOutletValidationError()
    if current.config_revision != request.expected_revision:
        raise ModelOutletConflictError()
    proposed = apply_outlet_patch(current, request)
    if proposed.identity.display_name != current.identity.display_name:
        if any(row["model_id"] != model_id for row in get_models_by_display_name(proposed.identity.display_name, tenant_id)):
            raise ModelOutletConflictError()
    credentials = {"api_key": request.api_key} if "api_key" in request.model_fields_set else {}
    row = get_model_by_model_id(model_id, tenant_id) or {}
    key, headers = _patch_credentials(request, row.get("api_key"), row.get("http_headers") or {})
    if "http_headers" in request.model_fields_set or "api_key" in request.model_fields_set:
        credentials["http_headers"] = headers
    status = request.connect_status
    if status is not None:
        credentials["connect_status"] = status
    revision = update_resolved_model_record(proposed, request.expected_revision, user_id, tenant_id,
                                           registered_references=refs, replacement_base=reselect_outlet_profile(current, request)
                                           if request.profile_selection is not None else None, **credentials)
    data = proposed.model_dump(mode="json")
    data["config_revision"] = revision
    return {"model_id": model_id, "config_revision": revision, "profile": data,
            "has_credential": has_model_outlet_credential(model_id, tenant_id),
            "http_header_names": sorted(credentials.get("http_headers", (get_model_by_model_id(model_id, tenant_id) or {}).get("http_headers") or {}))}
