"""Focused provider-cache tests.

W3 stable-prefix ordering and fingerprints are ContextManager evidence.  This
module verifies only provider capability, request directives, and usage metrics.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


_SDK_ROOT = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
for package_name, package_path in (
    ("nexent", _SDK_ROOT),
    ("nexent.core", _SDK_ROOT / "core"),
    ("nexent.core.models", _SDK_ROOT / "core" / "models"),
):
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package

_SPEC = importlib.util.spec_from_file_location(
    "nexent.core.models.prompt_cache", _SDK_ROOT / "core" / "models" / "prompt_cache.py"
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

from nexent.core.models.prompt_cache import (
    apply_cache_directives,
    cache_directive_advice,
    extract_prompt_cache_usage,
    resolve_prompt_cache_profile,
)


def test_known_provider_profile_is_structured_and_unknown_provider_is_disabled():
    profile = resolve_prompt_cache_profile("openai")
    assert profile["mode"] == "openai_automatic"
    assert profile["enabled"] is True
    assert resolve_prompt_cache_profile("unrecognized-provider") is None


def test_provider_cache_advice_uses_profile_only():
    advice = cache_directive_advice({"mode": "openai_automatic", "enabled": True})
    assert advice.supported is True
    assert advice.mode == "openai_automatic"
    assert advice.directives == ()


def test_unknown_capability_emits_no_directive():
    advice = cache_directive_advice(None)
    request = apply_cache_directives({"messages": []}, advice)
    assert advice.supported is False
    assert request == {"messages": []}


def test_anthropic_directive_is_applied_to_last_leading_stable_message_only():
    advice = cache_directive_advice({"mode": "anthropic_ephemeral", "enabled": True})
    request = apply_cache_directives(
        {
            "messages": [
                {"role": "system", "content": "policy"},
                {"role": "developer", "content": "agent"},
                {"role": "user", "content": "question"},
            ]
        },
        advice,
    )
    assert request["messages"][1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert request["messages"][2]["content"] == "question"


def test_directive_application_preserves_dynamic_tool_message_fields():
    advice = cache_directive_advice({"mode": "anthropic_ephemeral", "enabled": True})
    request = apply_cache_directives(
        {
            "messages": [
                {"role": "system", "content": "policy"},
                {"role": "tool", "content": "result", "tool_call_id": "call-1", "name": "search"},
            ]
        },
        advice,
    )
    assert request["messages"][1]["tool_call_id"] == "call-1"
    assert request["messages"][1]["name"] == "search"


def test_cache_usage_extracts_metrics_and_estimates_only_declared_discount():
    usage = {"prompt_tokens_details": {"cached_tokens": 40}}
    result = extract_prompt_cache_usage(
        usage, 100, capability_profile={"mode": "openai_automatic", "cached_input_discount": 0.5}
    )
    assert result.cached_input_tokens == 40
    assert result.uncached_input_tokens == 60
    assert result.provider_cache_hit is True
    assert result.hit_ratio == pytest.approx(0.4)
    assert result.estimated_saved_input_tokens == 20
    assert result.estimated_input_savings_ratio == pytest.approx(0.2)


def test_missing_metrics_never_reports_a_provider_cache_hit():
    result = extract_prompt_cache_usage({"prompt_tokens": 100}, 100)
    assert result.cached_input_tokens == 0
    assert result.provider_cache_hit is False
    assert result.metrics_source == "capability_unknown"
