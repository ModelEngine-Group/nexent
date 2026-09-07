from __future__ import annotations

import pytest

from nexent.core.models.final_request_budget import (
    CalibrationKey,
    CalibrationStore,
    FinalRequestIdentity,
    FinalRequestMeter,
    FinalRequestOverHardBudget,
    RequestSideEffectGuard,
    build_final_request_shape,
)


def _identity(model="qwen3.7-plus"):
    return FinalRequestIdentity(
        endpoint_fingerprint="endpoint",
        credential_scope_fingerprint="scope",
        canonical_model_id=f"dashscope:{model}",
        provider="dashscope",
        model_name=model,
        w1_fingerprint="w1",
        w2_fingerprint="w2",
    )


def test_ac_p2_001_shape_fingerprint_ignores_transport_but_not_semantics():
    base = {"model": "m", "messages": [{"role": "user", "content": "hello"}]}
    first = build_final_request_shape({**base, "stream": True, "stream_options": {"include_usage": True}})
    second = build_final_request_shape({**base, "stream": False})
    changed = build_final_request_shape({**base, "response_format": {"type": "json_object"}})

    assert first.fingerprint == second.fingerprint
    assert changed.fingerprint != first.fingerprint


def test_ac_p2_002_unified_components_cover_tools_media_reasoning_and_other():
    shape = build_final_request_shape(
        {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "你好 code {}"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,secret"}},
                    ],
                }
            ],
            "tools": [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}],
            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}, "semantic_flag": "x"},
        }
    )

    assert shape.request_shape == "tools_media"
    assert shape.components.message_text > 0
    assert shape.components.message_framing > 0
    assert shape.components.tools > 0
    assert shape.components.media == 256
    assert shape.components.reasoning > 0
    assert shape.components.other_semantic > 0
    assert "secret" not in repr(shape)


def test_ac_p5_002_generation_controls_are_not_prompt_tokens():
    base = build_final_request_shape({
        "messages": [{"role": "user", "content": "hello"}],
    })
    controlled = build_final_request_shape({
        "model": "Qwen/Qwen3.6-27B",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 1,
        "temperature": 0,
        "top_p": 0.9,
        "seed": 7,
    })

    assert controlled.components.raw_total == base.components.raw_total
    assert controlled.fingerprint != base.fingerprint


def test_ac_p5_002_tools_include_provider_protocol_envelope():
    without_tools = build_final_request_shape({
        "messages": [{"role": "user", "content": "weather"}],
    })
    with_tools = build_final_request_shape({
        "messages": [{"role": "user", "content": "weather"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "weather",
                "parameters": {"type": "object"},
            },
        }],
    })

    assert with_tools.components.tools >= 208
    assert with_tools.components.raw_total > without_tools.components.raw_total + 208


def test_ac_p2_004_exact_boundary_and_no_over_hard_dispatch_decision():
    meter = FinalRequestMeter(CalibrationStore(minimum_samples=2))
    kwargs = {"model": "m", "messages": [{"role": "user", "content": "x"}]}

    at_boundary = meter.measure(
        kwargs, identity=_identity(), soft_budget=9, hard_budget=10, provider_count=10
    )
    assert at_boundary.soft_exceeded is True
    assert at_boundary.hard_exceeded is False

    over = meter.measure(
        kwargs, identity=_identity(), soft_budget=9, hard_budget=10, provider_count=11
    )
    assert over.hard_exceeded is True


def test_ac_p2_008_usage_is_deduplicated_by_own_physical_request_id():
    store = CalibrationStore(minimum_samples=2)
    meter = FinalRequestMeter(store)
    identity = _identity()
    preflight = meter.measure(
        {"model": "m", "messages": [{"role": "user", "content": "hello"}]},
        identity=identity,
        soft_budget=1000,
        hard_budget=1000,
        request_id="physical-1",
    )

    assert meter.observe_usage(preflight, identity, provider_prompt_tokens=20) is True
    assert meter.observe_usage(preflight, identity, provider_prompt_tokens=20) is False
    key = CalibrationKey(
        "endpoint", "scope", "dashscope:qwen3.7-plus", preflight.request_shape, preflight.reasoning_mode
    )
    assert store.stats(key).sample_count == 1


def test_ac_p2_009_mature_p95_soft_and_p99_hard_are_independent():
    now = [1000.0]
    store = CalibrationStore(minimum_samples=20, clock=lambda: now[0])
    identity = _identity()
    key = CalibrationKey("endpoint", "scope", "dashscope:qwen3.7-plus", "text", "default")
    ratios = [1.0] * 18 + [1.5, 1.9]
    for index, ratio in enumerate(ratios):
        store.observe(
            key,
            request_id=f"r-{index}",
            raw_estimate=100,
            provider_prompt_tokens=int(100 * ratio),
        )
    stats = store.stats(key)
    assert stats.mature is True
    assert stats.p95 == 1.5
    assert stats.p99 == 1.9

    meter = FinalRequestMeter(store)
    preflight = meter.measure(
        {"messages": [{"role": "user", "content": "x"}]},
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
    )
    assert preflight.soft_count == pytest.approx(preflight.raw_estimate * 1.5, abs=1)
    assert preflight.hard_count == pytest.approx(preflight.raw_estimate * 1.9, abs=1)


def test_ac_p2_009_calibration_isolated_expiring_and_outlier_capped():
    now = [1000.0]
    store = CalibrationStore(minimum_samples=1, ttl_seconds=10, clock=lambda: now[0])
    key = CalibrationKey("e", "s", "m", "text", "default")
    other = CalibrationKey("e", "s", "other", "text", "default")
    store.observe(key, request_id="one", raw_estimate=1, provider_prompt_tokens=100)

    assert store.stats(key).p99 == 4.0
    assert store.stats(other).sample_count == 0
    now[0] = 1011.0
    assert store.stats(key).sample_count == 0


def test_ac_p2_005_side_effect_guard_is_monotonic_and_only_pristine_is_safe():
    guard = RequestSideEffectGuard()
    assert guard.recovery_safe is True
    guard.mark("response_started")
    assert guard.recovery_safe is False
    guard.mark("pristine")
    assert guard.state == "response_started"
    guard.mark("tool_effect")
    assert guard.state == "tool_effect"


def test_p10_ac_002_observed_anchor_estimates_only_appended_messages():
    meter = FinalRequestMeter(CalibrationStore(minimum_samples=20))
    identity = _identity()
    base = {
        "model": "m",
        "messages": [{"role": "user", "content": "first request"}],
        "tools": [{"type": "function", "function": {"name": "search"}}],
    }
    observed = meter.measure(
        base,
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
        provider_count=120,
    )
    assert observed.count_source == "provider"

    appended = meter.measure(
        {
            **base,
            "messages": [
                *base["messages"],
                {"role": "assistant", "content": "tool call"},
                {"role": "tool", "content": "tool result"},
            ],
        },
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
    )

    assert appended.count_source == "provider_anchor_delta"
    assert appended.anchor_input_tokens == 120
    assert appended.estimated_delta_tokens > 0
    assert appended.soft_count - 120 == pytest.approx(
        appended.estimated_delta_tokens * 1.15,
        abs=1,
    )
    assert meter.estimate_context_candidate(
        appended_messages := [
            *base["messages"],
            {"role": "assistant", "content": "tool call"},
            {"role": "tool", "content": "tool result"},
        ],
        base["tools"],
    ) == appended.soft_count
    assert len(appended_messages) == 3


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"tools": [{"type": "function", "function": {"name": "other"}}]}, "anchor_semantics_changed"),
        ({"response_format": {"type": "json_object"}}, "anchor_semantics_changed"),
    ],
)
def test_p10_ac_003_semantic_changes_invalidate_anchor(change, reason):
    meter = FinalRequestMeter(CalibrationStore(minimum_samples=20))
    identity = _identity()
    base = {"model": "m", "messages": [{"role": "user", "content": "first"}]}
    meter.measure(
        base,
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
        provider_count=100,
    )

    preflight = meter.measure(
        {**base, **change},
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
    )

    assert preflight.count_source == "estimated"
    assert preflight.anchor_invalidation_reason == reason


def test_p10_ac_003_history_rewrite_invalidates_anchor():
    meter = FinalRequestMeter(CalibrationStore(minimum_samples=20))
    identity = _identity()
    meter.measure(
        {"messages": [{"role": "user", "content": "old"}]},
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
        provider_count=100,
    )

    rewritten = meter.measure(
        {"messages": [{"role": "user", "content": "summary"}]},
        identity=identity,
        soft_budget=10_000,
        hard_budget=10_000,
    )

    assert rewritten.count_source == "estimated"
    assert rewritten.anchor_invalidation_reason == "anchor_non_append_only"
