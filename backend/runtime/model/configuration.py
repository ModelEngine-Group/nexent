# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep every LLM configuration writer on the resolved outlet storage format."""

from contracts.errors.exceptions import ModelOutletValidationError
from infrastructure.rdb.model_records import create_model_record, get_model_by_model_id, update_model_record
from nexent.core.model_service.profiles.parameter_schema import (
    ParameterValidationError,
    validate_sampling_parameters,
)
from runtime.model.outlet_legacy import create_legacy_llm_outlet, update_legacy_llm_outlet


def _validate_configured_sampling(data):
    try:
        validate_sampling_parameters(data)
        extra_params = data.get("extra_params")
        custom = extra_params.get("__custom__") if isinstance(extra_params, dict) else None
        if isinstance(custom, dict):
            validate_sampling_parameters(custom)
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None


def create_model_configuration(data, user_id, tenant_id):
    _validate_configured_sampling(data)
    if data.get("model_type") in {"llm", "chat"}:
        return create_legacy_llm_outlet(data, user_id, tenant_id)
    return create_model_record(data, user_id, tenant_id)


def update_model_configuration(model_id, changes, user_id=None, tenant_id=None):
    _validate_configured_sampling(changes)
    record = get_model_by_model_id(model_id, tenant_id=tenant_id)
    if record is None:
        raise LookupError("MODEL_OUTLET_NOT_FOUND")
    if record.get("model_type") in {"llm", "chat"}:
        return update_legacy_llm_outlet(record, changes, user_id, tenant_id)
    return update_model_record(model_id, changes, user_id, tenant_id)
