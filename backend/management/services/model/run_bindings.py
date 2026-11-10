# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve tenant model bindings and translate records into SDK configuration."""

from contracts.constants.environment import LLM_INCLUDE_LOGPROBS
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from management.db.model.repository import get_model_records
from management.services.configuration.tenant.settings import tenant_config_manager
from infrastructure.agent_model_config import (
    _build_extra_body as _build_extra_body,
    _is_thinking_enabled as _is_thinking_enabled,
    _resolve_model_reasoning_budget as _resolve_model_reasoning_budget,
    _resolve_model_reasoning_effort as _resolve_model_reasoning_effort,
    _resolve_reasoning_capability as _resolve_reasoning_capability,
    create_model_config_from_record as create_model_config_from_record,
    create_tenant_default_model_config,
)


async def create_model_config_list(tenant_id, *, versions=None):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = [create_model_config_from_record(record) for record in records]
    if versions is not None:
        for config, record in zip(model_list, records):
            revision = record.get("update_time") or record.get("create_time")
            if hasattr(revision, "isoformat"):
                revision = revision.isoformat()
            versions.setdefault(config.cite_name, (record.get("model_id"), revision or "legacy"))
    # Older Agent records reference one of these aliases instead of a catalog model.
    default_record = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id,
    )
    model_list.extend(
        create_tenant_default_model_config(default_record, alias, include_logprobs=LLM_INCLUDE_LOGPROBS)
        for alias in ("main_model", "sub_model")
    )
    return model_list
