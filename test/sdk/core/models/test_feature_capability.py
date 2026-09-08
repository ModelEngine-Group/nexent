from nexent.core.models.feature_capability import (
    apply_reasoning_request_policy,
    extract_provider_feature_candidate,
    resolve_effective_feature_policy,
    resolve_feature_capabilities,
)


def _profile(version="test@1", reasoning=True, cache=True):
    return {
        "profile_version": version,
        "reasoning": {
            "supported": reasoning,
            "mode": "toggle" if reasoning else "none",
            "request_style": "extra_body_enable_thinking" if reasoning else "none",
            "efforts": [],
        },
        "prompt_cache": {
            "supported": cache,
            "mode": "provider_automatic" if cache else "none",
            "metrics_available": cache,
        },
        "evidence": ["https://example.test/official"],
    }


def test_openai_standard_model_object_has_no_feature_candidate():
    assert extract_provider_feature_candidate({
        "id": "gpt-example", "object": "model", "created": 1, "owned_by": "owner"
    }) is None


def test_provider_extensions_are_allow_listed_and_normalized():
    candidate = extract_provider_feature_candidate({
        "id": "qwen-test",
        "api_key": "must-not-survive",
        "capabilities": {
            "supports_reasoning": True,
            "supports_prompt_cache": True,
            "supported_parameters": ["enable_thinking", "cache_control"],
        },
    })
    assert candidate["reasoning"]["request_style"] == "extra_body_enable_thinking"
    assert candidate["prompt_cache"]["mode"] == "anthropic_ephemeral"
    assert "api_key" not in str(candidate)


def test_conflicting_extension_fails_closed_for_affected_branch():
    candidate = extract_provider_feature_candidate({
        "supports_reasoning": False,
        "supported_parameters": ["reasoning_effort"],
    })
    assert candidate["reasoning"]["supported"] is None
    assert "conflicting_reasoning_extension" in candidate["warnings"]


def test_resolution_precedence_provider_then_exact_then_family_then_unknown():
    exact = {("factory", "model-a"): _profile("exact@1")}
    family = ({"provider": "factory", "pattern": r"model-.+", **_profile("family@1")},)
    candidate = extract_provider_feature_candidate({"supports_reasoning": False})

    provider_result = resolve_feature_capabilities(
        "factory", "model-a", provider_candidate=candidate,
        exact_catalog=exact, family_rules=family, catalog_revision="r1",
    )
    assert provider_result["source"] == "provider_extension"
    assert provider_result["reasoning"]["supported"] is False

    exact_result = resolve_feature_capabilities(
        "factory", "model-a", exact_catalog=exact, family_rules=family,
    )
    assert exact_result["source"] == "catalog_exact"

    family_result = resolve_feature_capabilities(
        "factory", "model-b", exact_catalog=exact, family_rules=family,
    )
    assert family_result["source"] == "catalog_family"

    unknown = resolve_feature_capabilities(
        "other", "model-b", exact_catalog=exact, family_rules=family,
    )
    assert unknown["source"] == "unknown"
    assert unknown["prompt_cache"]["supported"] is None


def test_family_exclusion_and_factory_boundary_are_enforced():
    rules = ({
        "provider": "factory",
        "pattern": r"qwen-.+",
        "exclusions": (r"qwen-unsafe",),
        **_profile(),
    },)
    assert resolve_feature_capabilities("factory", "qwen-unsafe", family_rules=rules)["source"] == "unknown"
    assert resolve_feature_capabilities("other", "qwen-good", family_rules=rules)["source"] == "unknown"


def test_p8_012_confirmed_toggle_and_effort_capabilities_default_on():
    toggle = _profile()
    toggle_policy = resolve_effective_feature_policy(toggle)
    assert toggle_policy["reasoning"] == {
        "supported": True,
        "enabled": True,
        "mode": "toggle",
        "request_style": "extra_body_enable_thinking",
        "effort": None,
    }
    assert toggle_policy["prompt_cache"]["enabled"] is True
    assert toggle_policy["source"] == "nexent_default"

    effort = _profile()
    effort["reasoning"].update({
        "mode": "effort",
        "request_style": "openai_reasoning_effort",
        "efforts": ["low", "medium", "high"],
        "default_effort": "medium",
    })
    effort_policy = resolve_effective_feature_policy(effort)
    assert effort_policy["reasoning"]["enabled"] is True
    assert effort_policy["reasoning"]["effort"] == "medium"


def test_p8_013_preferences_can_narrow_but_not_expand_capabilities():
    profile = _profile(reasoning=False, cache=False)
    policy = resolve_effective_feature_policy(
        profile,
        {"reasoning": {"enabled": True}, "prompt_cache": {"enabled": True}},
    )
    assert policy["reasoning"]["enabled"] is False
    assert policy["prompt_cache"]["enabled"] is False
    assert policy["warnings"] == [
        "reasoning_enable_unsupported",
        "prompt_cache_enable_unsupported",
    ]

    always = _profile()
    always["reasoning"].update({"mode": "always", "request_style": "none"})
    policy = resolve_effective_feature_policy(always, {"reasoning": {"enabled": False}})
    assert policy["reasoning"]["enabled"] is True
    assert policy["warnings"] == ["reasoning_disable_unsupported"]


def test_p8_014_effective_policy_maps_to_wire_parameter_names():
    effort_request = apply_reasoning_request_policy(
        {"messages": [], "extra_body": {"logprobs": True, "enable_thinking": False}},
        {
            "reasoning": {
                "enabled": True,
                "mode": "effort",
                "request_style": "openai_reasoning_effort",
                "effort": "medium",
            }
        },
    )
    assert effort_request["reasoning_effort"] == "medium"
    assert effort_request["extra_body"] == {"logprobs": True}

    toggle_request = apply_reasoning_request_policy(
        {"messages": [], "extra_body": {"logprobs": True}},
        {
            "reasoning": {
                "enabled": True,
                "mode": "toggle",
                "request_style": "extra_body_enable_thinking",
            }
        },
    )
    assert toggle_request["extra_body"] == {"logprobs": True, "enable_thinking": True}
