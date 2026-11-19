# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve tenant model bindings and translate records into SDK configuration."""

from infrastructure.model_adapter import restore_model_snapshot
from contracts.model_names import get_model_name_from_config
from nexent.core.models.prompt_cache import resolve_prompt_cache_profile
from nexent.core.agents.contracts.config import ModelConfig
from infrastructure.system_configuration.runtime import get_config_snapshot
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
    create_tenant_default_model_config, _resolved_model_config, model_record_revision,
)


async def create_model_config_list(tenant_id, *, versions=None):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = [create_model_config_from_record(record) for record in records if record.get("model_id") is None or record.get("profile_schema_version") is not None]
    extra_body = {"logprobs": True} if get_config_snapshot().get("LLM_INCLUDE_LOGPROBS") else None
    # fit for old version, main_model and sub_model use default model
    main_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
    # Reuse the row already captured for this run, including its credential and revision.
    if main_model_config.get("profile_schema_version") is not None:
        main_model_config = next((record for record in records
                                  if record.get("model_id") == main_model_config.get("model_id")), main_model_config)
    if (main_model_config.get("model_id") is not None
            and main_model_config.get("profile_schema_version") is None):
        # A failed default outlet is not an implicit fallback for a selected outlet.
        _capture_model_versions(versions, model_list, records, main_model_config)
        return model_list
    main_snapshot = restore_model_snapshot(main_model_config, tenant_id)
    if main_snapshot is not None:
        model_list.extend(
            _resolved_model_config(
                main_model_config,
                main_snapshot,
                cite_name=alias,
                extra_body=extra_body,
            )
            for alias in ("main_model", "sub_model")
        )
    else:
        main_prompt_cache = resolve_prompt_cache_profile(main_model_config.get("model_factory"))
        for alias in ("main_model", "sub_model"):
            model_list.append(ModelConfig(
                cite_name=alias, api_key=main_model_config.get("api_key", ""),
                model_name=get_model_name_from_config(main_model_config) if main_model_config.get("model_name") else "",
                url=main_model_config.get("base_url", ""), ssl_verify=main_model_config.get("ssl_verify", True),
                model_factory=main_model_config.get("model_factory"),
                timeout_seconds=main_model_config.get("timeout_seconds"),
                concurrency_limit=main_model_config.get("concurrency_limit"),
                prompt_cache=main_prompt_cache, extra_body=extra_body,
            ))

    _capture_model_versions(versions, model_list, records, main_model_config)
    return model_list


def _capture_model_versions(versions, model_list, records, default_record):
    if versions is None:
        return
    records_by_alias = {row.get("display_name"): row for row in reversed(records)}
    for config in model_list:
        row = records_by_alias.get(config.cite_name, default_record)
        versions.setdefault(config.cite_name, (row.get("model_id"), model_record_revision(row)))
