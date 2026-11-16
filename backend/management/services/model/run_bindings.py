# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve tenant model bindings and translate records into SDK configuration."""

import logging
from typing import Any, Dict, Optional

from contracts.constants.environment import LLM_INCLUDE_LOGPROBS, MODEL_RESPONSE_DIAGNOSTIC_CHUNKS
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from management.db.model.repository import get_model_records
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.names import add_repo_to_name, get_model_name_from_config
from nexent.core.agents.agent_model import ModelConfig
from management.services.model.adapter import restore_model_snapshot
from nexent.core.model_service.compatibility.legacy_config import (legacy_extra_body, legacy_reasoning_budget, legacy_reasoning_effort, legacy_thinking_enabled)
from nexent.core.models.prompt_cache import resolve_prompt_cache_profile

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)

COMMON_REASONING_LEVELS = ("low", "medium", "high")

COMMON_REASONING_DEFAULT = "auto"






def _resolve_reasoning_capability(
    model_name: str,
    base_url: Optional[str],
    provider_hint: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Resolve catalog reasoning metadata without coupling import-time setup."""
    try:
        from configs.model_catalog_loader import resolve_reasoning_capability
    except ImportError:
        return None
    return resolve_reasoning_capability(
        model_name=model_name,
        base_url=base_url,
        provider_hint=provider_hint,
    )






def create_model_config_from_record(record):
    """Build a complete provider binding from one exact tenant model record."""
    snapshot = restore_model_snapshot(record, record.get("tenant_id"))
    if snapshot is not None:
        return _resolved_model_config(record, snapshot)
    model_name = add_repo_to_name(
        model_repo=record["model_repo"],
        model_name=record["model_name"],
    )
    reasoning_capability = _resolve_reasoning_capability(
        model_name=model_name,
        base_url=record.get("base_url"),
        provider_hint=record.get("model_factory"),
    )
    return ModelConfig(cite_name=record["display_name"],
                        diagnostic_chunks_enabled=MODEL_RESPONSE_DIAGNOSTIC_CHUNKS,
                        api_key=record.get("api_key", ""),
                        model_name=model_name,
                        url=record["base_url"],
                        ssl_verify=record.get("ssl_verify", True),
                        model_factory=record.get("model_factory"),
                        timeout_seconds=record.get("timeout_seconds"),
                        concurrency_limit=record.get("concurrency_limit"),
                        prompt_cache=resolve_prompt_cache_profile(
                            record.get("model_factory")),
                        # W1 step 6: pass capacity columns through so SDK can
                        # honor operator-configured values end to end.
                        max_output_tokens=record.get("max_output_tokens"),
                        max_tokens=record.get("max_tokens"),
                        context_window_tokens=record.get("context_window_tokens"),
                        max_input_tokens=record.get("max_input_tokens"),
                        default_output_reserve_tokens=record.get("default_output_reserve_tokens"),
                        tokenizer_family=record.get("tokenizer_family"),
                        capacity_source=record.get("capacity_source"),
                        capability_profile_version=record.get("capability_profile_version"),
                        # v2.6.0: pass inference params so model-level
                        # temperature/top_p/extra_params flow into SDK.
                        temperature=record.get("temperature"),
                        top_p=record.get("top_p"),
                        enable_thinking=legacy_thinking_enabled(record.get("extra_params")),
                        reasoning_capability=reasoning_capability,
                        reasoning_effort=legacy_reasoning_effort(
                            record.get("extra_params"), reasoning_capability
                        ),
                        reasoning_budget_tokens=legacy_reasoning_budget(
                            record.get("extra_params"), reasoning_capability
                        ),
                        extra_body=legacy_extra_body(record.get("extra_params")))


async def create_model_config_list(tenant_id):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = [create_model_config_from_record(record) for record in records if record.get("model_id") is None or record.get("profile_schema_version") is not None]
    extra_body = {"logprobs": True} if LLM_INCLUDE_LOGPROBS else None
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
        return model_list
    main_snapshot = restore_model_snapshot(main_model_config, tenant_id)
    if main_snapshot is not None:
        model_list.extend(_resolved_model_config(main_model_config, main_snapshot, cite_name=alias)
                          for alias in ("main_model", "sub_model"))
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

    return model_list


def _resolved_model_config(record, snapshot, cite_name=None):
    """Map one frozen outlet into the existing Agent configuration contract."""
    from management.services.model.outlet_projection import project_saved_outlet

    output_reserve = snapshot.parameter_values.get("max_output_tokens")
    if output_reserve is None:
        output_reserve = snapshot.context_configuration.output_reserve_tokens
    return ModelConfig(
        cite_name=cite_name if cite_name is not None else record["display_name"], api_key=record.get("api_key") or "",
        model_name=snapshot.identity.request_model_id, url=snapshot.connection.base_url,
        http_headers=record.get("http_headers") or {},
        resolved_profile=snapshot, model_factory=snapshot.identity.provider_id,
        reasoning_capability=project_saved_outlet(record)["reasoning_capability"],
        temperature=snapshot.parameter_values.get("temperature"), top_p=snapshot.parameter_values.get("top_p"),
        enable_thinking=snapshot.parameter_values.get("enable_thinking") is True,
        reasoning_effort=(snapshot.parameter_values.get("reasoning_effort")
                          if snapshot.parameter_values.get("reasoning_effort") in
                          {"auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"} else None),
        reasoning_budget_tokens=snapshot.parameter_values.get("reasoning_budget_tokens"),
        context_window_tokens=snapshot.capabilities.context.combined_window,
        max_input_tokens=snapshot.capabilities.context.input_limit,
        max_output_tokens=snapshot.capabilities.context.output_limit,
        default_output_reserve_tokens=output_reserve,
        tokenizer_family=snapshot.context_configuration.tokenizer_family,
        capacity_source=snapshot.context_configuration.capacity_source,
        capability_profile_version=snapshot.context_configuration.capability_profile_version,
    )
