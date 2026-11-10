# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve tenant model bindings and translate records into SDK configuration."""

from contracts.constants.environment import LLM_INCLUDE_LOGPROBS
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from management.db.model.repository import get_model_records
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.names import get_model_name_from_config
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.models.prompt_cache import resolve_prompt_cache_profile
from infrastructure.agent_model_config import (
    _build_extra_body as _build_extra_body,
    _is_thinking_enabled as _is_thinking_enabled,
    _resolve_model_reasoning_budget as _resolve_model_reasoning_budget,
    _resolve_model_reasoning_effort as _resolve_model_reasoning_effort,
    _resolve_reasoning_capability as _resolve_reasoning_capability,
    create_model_config_from_record as create_model_config_from_record,
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
    extra_body = {"logprobs": True} if LLM_INCLUDE_LOGPROBS else None
    # fit for old version, main_model and sub_model use default model
    main_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id
    )
    main_prompt_cache = resolve_prompt_cache_profile(
        main_model_config.get("model_factory")
    )
    model_list.append(
        ModelConfig(
            cite_name="main_model",
            api_key=main_model_config.get("api_key", ""),
            model_name=get_model_name_from_config(main_model_config)
            if main_model_config.get("model_name")
            else "",
            url=main_model_config.get("base_url", ""),
            ssl_verify=main_model_config.get("ssl_verify", True),
            model_factory=main_model_config.get("model_factory"),
            timeout_seconds=main_model_config.get("timeout_seconds"),
            concurrency_limit=main_model_config.get("concurrency_limit"),
            prompt_cache=main_prompt_cache,
            extra_body=extra_body,
        )
    )
    model_list.append(
        ModelConfig(
            cite_name="sub_model",
            api_key=main_model_config.get("api_key", ""),
            model_name=get_model_name_from_config(main_model_config)
            if main_model_config.get("model_name")
            else "",
            url=main_model_config.get("base_url", ""),
            ssl_verify=main_model_config.get("ssl_verify", True),
            model_factory=main_model_config.get("model_factory"),
            timeout_seconds=main_model_config.get("timeout_seconds"),
            concurrency_limit=main_model_config.get("concurrency_limit"),
            prompt_cache=main_prompt_cache,
            extra_body=extra_body,
        )
    )

    return model_list
