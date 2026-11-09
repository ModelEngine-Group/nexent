# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatible controls for custom OpenAI hosts, bounded by explicit preferences."""

from functools import lru_cache

from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules


@lru_cache(maxsize=1)
def _model_shutdown_preferences():
    from nexent.core.model_service.profiles.resolver import load_profile_catalog

    catalog = load_profile_catalog()
    return {key: atom.capabilities["reasoning"]["can_disable"] for key, atom in catalog.models.items()
            if atom.capabilities["reasoning"]["can_disable"] is not None}


def custom_thinking_rule():
    """Expose a compatible default format without claiming provider qualification."""
    return {"key": "enable_thinking", "schema": {"type": "boolean"}, "visible": True,
            "editable": True, "required": False, "allowed_scopes": ["outlet", "conversation"],
            "ui_group": "reasoning", "owner": "provider",
            "source": {"ref": "custom_provider_thinking_v1", "version": 1},
            "api_binding": {"path": "/enable_thinking", "transform_ref": "identity_v1", "transform_version": 1}}


def custom_thinking_allowed(reasoning):
    """Unknown shutdown capability remains configurable on a custom provider."""
    return reasoning["status"] == "supported" and reasoning.get("can_disable") is not False


def ensure_outlet_parameter_rules(profile):
    """Complete old custom outlets without replacing their saved provider policy."""
    profile = ensure_outlet_sampling_rules(profile)
    if profile.bindings.protocol.ref != "openai_chat_completions":
        return profile
    data = profile.model_dump(mode="json")
    reasoning = data["capabilities"]["reasoning"]
    # Apply only the explicit shutdown preference; other frozen facts stay intact.
    if profile.provider_key is None and reasoning["can_disable"] is None:
        reasoning["can_disable"] = _model_shutdown_preferences().get(profile.model_profile_key)
    rules = data["parameter_rules"]
    has_toggle = any(rule["key"] == "enable_thinking" for rule in rules)
    has_effort_off = any(rule["key"] == "reasoning_effort" and
                        "none" in rule["schema"].get("enum", []) for rule in rules)
    # Saved manual parameters retain ownership of the fallback's wire path.
    has_extra_toggle = any(extra["path"] == "/enable_thinking" or
                           extra["path"].startswith("/enable_thinking/")
                           for extra in data["extra_api_parameters"])
    if (profile.provider_key is None and custom_thinking_allowed(reasoning)
            and not has_toggle and not has_effort_off and not has_extra_toggle):
        rules.append(custom_thinking_rule())
        controls = reasoning["controls"] or []
        reasoning["controls"] = [{"mode": "toggle", "parameter_key": "enable_thinking", "values": [False, True]},
                                 *controls]
    return profile.__class__.model_validate(data)
