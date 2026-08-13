"""Regression tests for ``_config_to_context``: falsy-but-valid sampling values.

The bridge coalesces per-call ``construct_extras`` with ``cfg``-level values
before building the typed context. Coalescing must use ``_coalesce`` (first
non-``None``), NOT ``a or b`` — otherwise an explicit ``temperature=0`` (a
common "deterministic" setting) or ``top_p=0`` is silently dropped and the
adapter falls back to the model's own default. These tests pin that behavior.
"""
import os
import sys

# backend/ on path so `services.model_gateway_service` imports cleanly.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from services.model_gateway_service import _config_to_context  # noqa: E402


def _cfg(**over):
    cfg = {"base_url": "u", "api_key": "k", "model_factory": "openai"}
    cfg.update(over)
    return cfg


# ---- LLM sampling: falsy-but-valid values must round-trip ----

def test_temperature_zero_round_trips():
    """temperature=0 (deterministic) must reach sampling, not be dropped by `or`."""
    ctx = _config_to_context(_cfg(), "llm", "llm", None,
                            model_name="m", temperature=0, top_p=0.9)
    assert ctx.sampling.temperature == 0
    assert ctx.sampling.top_p == 0.9


def test_top_p_zero_round_trips():
    ctx = _config_to_context(_cfg(), "llm", "llm", None,
                            model_name="m", top_p=0)
    assert ctx.sampling.top_p == 0


def test_max_output_tokens_zero_round_trips():
    ctx = _config_to_context(_cfg(), "llm", "llm", None,
                            model_name="m", max_output_tokens=0)
    assert ctx.sampling.max_output_tokens == 0


def test_stream_false_round_trips():
    """stream=False is a real value, not 'unset' (unset is None)."""
    ctx = _config_to_context(_cfg(), "llm", "llm", None,
                            model_name="m", stream=False)
    assert ctx.sampling.stream is False


# ---- base / TTS numerics ----

def test_timeout_seconds_zero_round_trips():
    ctx = _config_to_context(_cfg(), "llm", "llm", None,
                            model_name="m", timeout_seconds=0)
    assert ctx.timeout_seconds == 0


def test_speed_ratio_zero_round_trips():
    ctx = _config_to_context(_cfg(), "tts", "tts", None,
                            model_name="m", speed_ratio=0)
    assert ctx.speed_ratio == 0.0


def test_speed_ratio_unset_defaults_to_one():
    ctx = _config_to_context(_cfg(), "tts", "tts", None, model_name="m")
    assert ctx.speed_ratio == 1.0


# ---- unset sampling stays None (model uses its own default) ----

def test_unset_sampling_fields_stay_none():
    ctx = _config_to_context(_cfg(), "llm", "llm", None, model_name="m")
    assert ctx.sampling.temperature is None
    assert ctx.sampling.top_p is None
    assert ctx.sampling.stream is None
    assert ctx.sampling.max_output_tokens is None


# ---- cfg-level values still apply when no per-call extra is given ----

def test_cfg_temperature_applies_when_no_per_call_override():
    ctx = _config_to_context(_cfg(temperature=0.5), "llm", "llm", None, model_name="m")
    assert ctx.sampling.temperature == 0.5


def test_per_call_override_wins_over_cfg():
    ctx = _config_to_context(_cfg(temperature=0.5), "llm", "llm", None,
                            model_name="m", temperature=0.2)
    assert ctx.sampling.temperature == 0.2
