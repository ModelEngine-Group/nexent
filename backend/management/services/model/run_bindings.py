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
from nexent.core.models.prompt_cache import resolve_prompt_cache_profile

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)

COMMON_REASONING_LEVELS = ("low", "medium", "high")

COMMON_REASONING_DEFAULT = "auto"


def _is_thinking_enabled(extra_params: Optional[Dict[str, Any]]) -> bool:
    """Return whether the model explicitly or implicitly enables reasoning."""
    if not isinstance(extra_params, dict):
        return False
    if isinstance(extra_params.get("enable_thinking"), bool):
        return extra_params["enable_thinking"]
    return isinstance(extra_params.get("reasoning_effort"), str) or isinstance(
        extra_params.get("reasoning_budget_tokens"), int
    )


def _build_extra_body(
    extra_params: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build extra_body for ModelConfig from model_record_t.extra_params.

    Merges __custom__ user-defined params into the top level so they flow
    into OpenAI chat.completions.create request body. Returns None when
    there is nothing to pass through so production behaviour is unchanged.
    """
    if not extra_params or not isinstance(extra_params, dict):
        return None
    extra_body = dict(extra_params)
    # These are dedicated ModelConfig fields, not provider request-body keys.
    extra_body.pop("reasoning_effort", None)
    extra_body.pop("reasoning_budget_tokens", None)
    custom = extra_body.pop("__custom__", None)
    if custom and isinstance(custom, dict):
        extra_body.update(custom)
    return extra_body if extra_body else None


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


def _resolve_model_reasoning_effort(
    extra_params: Optional[Dict[str, Any]],
    capability: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve the enabled model's effort from its supported profile."""
    if not isinstance(extra_params, dict) or not _is_thinking_enabled(extra_params):
        return None
    if extra_params.get("reasoning_effort") == "auto":
        return None
    if isinstance(capability, dict) and capability.get("status") == "supported":
        levels = capability.get("levels") or list(COMMON_REASONING_LEVELS)
        default = capability.get("default")
        if default not in levels:
            default = COMMON_REASONING_DEFAULT
    else:
        # Unknown/custom model IDs still use the common generic profile. The
        # provider remains the source of truth when a concrete value is sent.
        levels = list(COMMON_REASONING_LEVELS)
        default = COMMON_REASONING_DEFAULT
    saved = extra_params.get("reasoning_effort")
    if saved in levels:
        return saved
    # Auto is the universal fallback: omit the provider-specific effort so the
    # model can choose its own reasoning depth.
    return None if saved is None or default == COMMON_REASONING_DEFAULT else default


def _resolve_model_reasoning_budget(
    extra_params: Optional[Dict[str, Any]],
    capability: Optional[Dict[str, Any]],
) -> Optional[int]:
    """Resolve a persisted numeric reasoning budget within the source range."""
    if not isinstance(extra_params, dict) or not _is_thinking_enabled(extra_params):
        return None
    value = extra_params.get("reasoning_budget_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    controls = capability.get("controls") if isinstance(capability, dict) else None
    budget_control = next(
        (
            control
            for control in controls or []
            if isinstance(control, dict) and control.get("type") == "budget_tokens"
        ),
        None,
    )
    if isinstance(budget_control, dict):
        minimum = budget_control.get("min")
        maximum = budget_control.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int):
            return min(maximum, max(minimum, value))
    return value


def create_model_config_from_record(record):
    """Build a complete provider binding from one exact tenant model record."""
    model_name = add_repo_to_name(
        model_repo=record["model_repo"],
        model_name=record["model_name"],
    )
    reasoning_capability = _resolve_reasoning_capability(
        model_name=model_name,
        base_url=record.get("base_url"),
        provider_hint=record.get("model_factory"),
    )
    return ModelConfig(
        cite_name=record["display_name"],
        diagnostic_chunks_enabled=MODEL_RESPONSE_DIAGNOSTIC_CHUNKS,
        api_key=record.get("api_key", ""),
        model_name=model_name,
        url=record["base_url"],
        ssl_verify=record.get("ssl_verify", True),
        model_factory=record.get("model_factory"),
        timeout_seconds=record.get("timeout_seconds"),
        concurrency_limit=record.get("concurrency_limit"),
        prompt_cache=resolve_prompt_cache_profile(record.get("model_factory")),
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
        enable_thinking=_is_thinking_enabled(record.get("extra_params")),
        reasoning_capability=reasoning_capability,
        reasoning_effort=_resolve_model_reasoning_effort(
            record.get("extra_params"), reasoning_capability
        ),
        reasoning_budget_tokens=_resolve_model_reasoning_budget(
            record.get("extra_params"), reasoning_capability
        ),
        extra_body=_build_extra_body(record.get("extra_params")),
    )


async def create_model_config_list(tenant_id):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = [create_model_config_from_record(record) for record in records]
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
