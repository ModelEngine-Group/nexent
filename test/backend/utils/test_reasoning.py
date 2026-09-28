from utils.reasoning import (
    _control,
    _controls,
    normalize_reasoning_params,
    reasoning_controls,
    supports_reasoning,
)


def test_controls_support_legacy_levels_and_toggle_profiles():
    assert _controls(None) == []
    assert _controls({"status": "unsupported", "levels": ["high"]}) == []
    assert _controls({"status": "supported", "levels": ["low", "high"]}) == [
        {"type": "effort", "values": ["low", "high"]}
    ]
    assert _controls({"status": "supported", "control": "toggle"}) == [
        {"type": "toggle"}
    ]
    assert _controls({"status": "supported"}) == []
    assert _controls(
        {
            "status": "supported",
            "controls": [{"type": "effort", "values": ["low"]}, "ignored"],
        }
    ) == [{"type": "effort", "values": ["low"]}]


def test_control_lookup_and_support_status_follow_declared_controls():
    capability = {
        "status": "supported",
        "controls": [{"type": "budget_tokens", "min": 128, "max": 32768}],
    }

    assert supports_reasoning(capability) is True
    assert _control(capability, "budget_tokens") == capability["controls"][0]
    assert _control(capability, "effort") is None
    assert reasoning_controls(capability) == capability["controls"]
    assert supports_reasoning({"status": "supported"}) is False


def test_normalize_reasoning_params_fails_closed_for_unknown_capabilities():
    params = {
        "enable_thinking": True,
        "reasoning_effort": "high",
        "reasoning_budget_tokens": 4096,
        "custom": "keep",
    }

    result = normalize_reasoning_params(params, None)

    assert result == {"custom": "keep"}
    assert params["reasoning_effort"] == "high"


def test_normalize_reasoning_params_handles_disabled_and_invalid_effort():
    capability = {"status": "supported", "levels": ["low", "high"]}

    disabled = normalize_reasoning_params(
        {"enable_thinking": False, "reasoning_effort": "high", "custom": 1},
        capability,
    )
    invalid = normalize_reasoning_params(
        {"enable_thinking": True, "reasoning_effort": "medium"}, capability
    )

    assert disabled == {"enable_thinking": False, "custom": 1}
    assert invalid == {"enable_thinking": True, "reasoning_effort": "auto"}


def test_normalize_reasoning_params_clamps_budget_and_removes_effort():
    capability = {
        "status": "supported",
        "controls": [{"type": "budget_tokens", "min": 128, "max": 32768}],
    }

    result = normalize_reasoning_params(
        {
            "enable_thinking": True,
            "reasoning_effort": "high",
            "reasoning_budget_tokens": 65536,
        },
        capability,
    )

    assert result == {"enable_thinking": True, "reasoning_budget_tokens": 32768}


def test_normalize_reasoning_params_keeps_budget_without_declared_bounds():
    capability = {
        "status": "supported",
        "controls": [{"type": "budget_tokens"}],
    }

    result = normalize_reasoning_params(
        {"reasoning_budget_tokens": 4096, "reasoning_effort": "high"},
        capability,
    )

    assert result == {
        "enable_thinking": True,
        "reasoning_budget_tokens": 4096,
    }


def test_normalize_reasoning_params_removes_effort_when_only_budget_is_declared():
    capability = {
        "status": "supported",
        "controls": [{"type": "budget_tokens", "min": 128, "max": 32768}],
    }

    result = normalize_reasoning_params(
        {"enable_thinking": True, "reasoning_effort": "high"}, capability
    )

    assert result == {"enable_thinking": True}


def test_normalize_reasoning_params_infers_enabled_from_historical_effort():
    result = normalize_reasoning_params(
        {"reasoning_effort": "low"},
        {"status": "supported", "levels": ["low", "high"]},
    )

    assert result == {"enable_thinking": True, "reasoning_effort": "low"}
