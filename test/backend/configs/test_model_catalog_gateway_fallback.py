# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regressions for native-model lookup behind an unlisted compatible gateway."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from configs import model_catalog_loader as loader

GATEWAY = "https://gateway.example.invalid/v1"
OFFICIAL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.fixture
def catalog(monkeypatch):
    model = {
        "reasoning": True,
        "reasoning_options": [
            {"type": "toggle"},
            {"type": "effort", "values": ["low", "medium", "xhigh"]},
            {"type": "budget_tokens", "min": 0, "max": 262144},
        ],
    }
    data = {"providers": {
        "reseller": {"api": "https://reseller.invalid/v1", "models": {
            "qwen3.8-max": {"reasoning": True, "reasoning_options": ["high"]},
        }},
        "alibaba-cn": {"api": OFFICIAL, "models": {"qwen3.8-max": model}},
    }}
    monkeypatch.setattr(loader, "_load_models_dev_catalog", lambda: data)
    monkeypatch.setattr(loader, "get_provider_info", lambda name: (
        SimpleNamespace(base_url=OFFICIAL) if name == "dashscope" else None
    ))
    return data


def resolve(name="qwen3.8-max", url=GATEWAY, hint="OpenAI-API-Compatible"):
    return loader.resolve_reasoning_capability(name, url, hint)


@pytest.mark.parametrize("name", ["qwen3.8-max", " QWEN3.8-MAX ", "Qwen/qwen3.8-max"])
def test_unlisted_gateway_uses_native_model_without_native_transport(catalog, name):
    original = deepcopy(catalog)
    result = resolve(name)
    assert result is not None
    assert result["controls"] == [
        {"type": "toggle"},
        {"type": "effort", "values": ["low", "medium", "xhigh"]},
    ]
    assert result["levels"] == ["low", "medium", "xhigh"]
    assert result["control"] == "effort"
    assert result["default"] == "auto"
    assert result["source"] == "models_dev"
    assert result["provider_id"] == "OpenAI-API-Compatible"
    assert result["matched_api"] == GATEWAY
    assert result["matched_model_id"] == "qwen3.8-max"
    assert result["wire_format"] == "reasoning_effort"
    assert result["toggle_wire_format"] is None
    assert result["budget_wire_format"] is None
    assert result["effort_budgets"] == {}
    assert catalog == original


@pytest.mark.parametrize("hint,expected", [
    (None, "custom"), ("custom", "custom"),
    ("OpenAI-API-Compatible", "OpenAI-API-Compatible"), ("dashscope", "custom"),
])
def test_unmatched_url_does_not_acquire_a_native_provider_identity(catalog, hint, expected):
    result = resolve(hint=hint)
    assert result is not None
    assert result["provider_id"] == expected
    assert result["matched_api"] == GATEWAY


def test_matched_provider_and_longest_prefix_remain_authoritative(catalog):
    catalog["providers"]["gateway"] = {
        "api": GATEWAY, "models": {"qwen3.8-max": {"reasoning": False}},
    }
    assert resolve() is None
    catalog["providers"]["gateway"]["models"] = {}
    assert resolve() is None
    official = resolve(url=OFFICIAL + "/chat/completions")
    assert official["provider_id"] == "alibaba-cn"
    assert official["budget_wire_format"] == "thinking_budget"
    assert official["controls"][-1]["type"] == "budget_tokens"
    catalog["providers"]["narrower"] = {
        "api": OFFICIAL + "/private", "models": {},
    }
    assert resolve(url=OFFICIAL + "/private/v1") is None


def test_full_model_id_wins_over_leaf_alias_and_ambiguity_is_rejected(catalog):
    models = catalog["providers"]["alibaba-cn"]["models"]
    models["other/qwen3.8-max"] = {"reasoning": False}
    assert resolve() is not None
    assert resolve("third/qwen3.8-max") is None
    models["alias"] = {**deepcopy(models["qwen3.8-max"]), "id": "qwen3.8-max"}
    assert resolve() is None


@pytest.mark.parametrize("options", [
    None, [], [{"type": "budget_tokens", "min": 0, "max": 128}],
    [{"type": "budget_tokens", "min": "bad", "max": 128}],
    [{"type": "effort", "values": 123}],
])
def test_budget_only_and_unusable_profiles_do_not_enable_generic_controls(catalog, options):
    catalog["providers"]["alibaba-cn"]["models"]["qwen3.8-max"]["reasoning_options"] = options
    assert resolve() is None


def test_unknown_missing_and_unsupported_models_stay_unavailable(catalog):
    assert resolve("unlisted-model") is None
    assert resolve("qwen-does-not-exist") is None
    assert resolve("qwen3.8-max-preview") is None
    assert resolve(url=None, hint="custom") is None
    model = catalog["providers"]["alibaba-cn"]["models"]["qwen3.8-max"]
    model["reasoning"] = False
    assert resolve() is None


def test_declared_alias_matches_without_guessing_missing_model_ids(catalog):
    model = catalog["providers"]["alibaba-cn"]["models"]["qwen3.8-max"]
    model["model"] = "qwen-official-alias"
    assert resolve("qwen-official-alias")["matched_model_id"] == "qwen3.8-max"
    del catalog["providers"]["alibaba-cn"]
    assert resolve() is None


def test_toggle_only_native_declaration_remains_toggle_only(catalog):
    catalog["providers"]["alibaba-cn"]["models"]["qwen3.8-max"]["reasoning_options"] = [
        {"type": "toggle"},
    ]
    result = resolve()
    assert result["control"] == "toggle"
    assert result["controls"] == [{"type": "toggle"}]
    assert result["levels"] == []


@pytest.mark.parametrize("bad_entry", [None, "invalid-provider", []])
def test_malformed_provider_entries_do_not_hide_a_valid_native_model(catalog, bad_entry):
    catalog["providers"] = {"broken": bad_entry, **catalog["providers"]}
    result = resolve()
    assert result is not None
    assert result["levels"] == ["low", "medium", "xhigh"]
    assert result["matched_api"] == GATEWAY


@pytest.mark.parametrize("bad_models", [None, [], "invalid-model-map"])
def test_malformed_native_model_collections_are_unavailable(catalog, bad_models):
    catalog["providers"]["alibaba-cn"]["models"] = bad_models
    assert resolve() is None


@pytest.mark.parametrize("bad_model", [None, [], "invalid-model"])
def test_malformed_model_entries_do_not_hide_a_valid_native_model(catalog, bad_model):
    models = catalog["providers"]["alibaba-cn"]["models"]
    catalog["providers"]["alibaba-cn"]["models"] = {"broken": bad_model, **models}
    result = resolve()
    assert result is not None
    assert result["matched_model_id"] == "qwen3.8-max"
    assert result["provider_id"] == "OpenAI-API-Compatible"


@pytest.mark.parametrize("native", [None, SimpleNamespace(base_url="")])
def test_native_provider_without_metadata_never_uses_reseller_controls(catalog, monkeypatch, native):
    monkeypatch.setattr(loader, "get_provider_info", lambda _: native)
    assert resolve() is None


def test_effort_only_profile_keeps_gateway_factory_and_actual_url(catalog):
    catalog["providers"]["alibaba-cn"]["models"]["qwen3.8-max"]["reasoning_options"] = {
        "type": "effort", "values": ["low", "medium", "xhigh"],
    }
    result = resolve(url=GATEWAY + "/", hint="modelengine")
    assert result["controls"] == [{"type": "effort", "values": ["low", "medium", "xhigh"]}]
    assert result["provider_id"] == "modelengine"
    assert result["matched_api"] == GATEWAY
    assert result["toggle_wire_format"] is None
    assert result["budget_wire_format"] is None


@pytest.mark.parametrize("enabled", [True, False])
def test_resolved_gateway_controls_build_generic_sdk_parameters(catalog, enabled):
    from contracts.model import ReasoningCapability
    from management.services.model.reasoning import normalize_reasoning_params
    from nexent.core.models.openai_llm import OpenAIModel

    capability = ReasoningCapability.model_validate(resolve()).model_dump(mode="json")
    params = normalize_reasoning_params({
        "enable_thinking": enabled, "reasoning_effort": "xhigh", "reasoning_budget_tokens": 4096,
    }, capability)
    assert "reasoning_budget_tokens" not in params
    model = OpenAIModel.__new__(OpenAIModel)
    model.reasoning_capability = capability
    model.model_factory = "OpenAI-API-Compatible"
    model.model_id = "qwen3.8-max"
    model.api_base_url = GATEWAY
    model.reasoning_effort = params.get("reasoning_effort")
    model.reasoning_budget_tokens = None
    request = {"extra_body": model._translate_thinking_flag({"enable_thinking": enabled})}
    model._apply_reasoning_control(request)
    assert request == {
        "extra_body": {"enable_thinking": enabled},
        **({"reasoning_effort": "xhigh"} if enabled else {}),
    }


def test_legacy_migration_keeps_pre_gateway_matching_boundary(catalog):
    assert loader.resolve_reasoning_capability(
        "qwen3.8-max", GATEWAY, "custom", allow_gateway_fallback=False,
    ) is None
    assert loader.resolve_reasoning_capability(
        "qwen3.8-max", OFFICIAL, "alibaba-cn", allow_gateway_fallback=False,
    )["provider_id"] == "alibaba-cn"
    assert resolve() is not None  # Current gateway behavior remains enabled.
