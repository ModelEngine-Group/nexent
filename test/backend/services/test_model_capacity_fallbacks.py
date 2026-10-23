"""Capacity catalog fallbacks and optional telemetry regression tests."""

from unittest.mock import MagicMock, mock_open

import pytest
from contracts.model import CapacitySuggestionMatchKind
from management.services.model import capacity


@pytest.fixture(autouse=True)
def isolate_capacity_state(monkeypatch):
    monkeypatch.setattr(capacity, "_LITELLM_CACHE", {})
    monkeypatch.setattr(capacity, "_CAPACITY_SUGGESTION_ERROR_EMITTED", set())


def test_catalog_file_is_loaded_once(monkeypatch):
    reader = mock_open(read_data='{"model": {"max_input_tokens": 32000}}')
    monkeypatch.setattr(capacity, "_LITELLM_CACHE", None)
    monkeypatch.setattr("builtins.open", reader)
    first = capacity._litellm_cache()
    assert first == {"model": {"max_input_tokens": 32000}}
    assert capacity._litellm_cache() is first
    reader.assert_called_once_with(capacity.NEXENT_LITELLM_JSON, "r", encoding="utf-8")


def test_missing_catalog_is_cached_as_empty(monkeypatch):
    reader = MagicMock(side_effect=FileNotFoundError("missing catalog"))
    monkeypatch.setattr(capacity, "_LITELLM_CACHE", None)
    monkeypatch.setattr("builtins.open", reader)
    assert capacity._litellm_cache() == {}
    assert capacity._litellm_cache() == {}
    assert reader.call_count == 1


@pytest.mark.parametrize(
    "raw,expected",
    [(None, None), ("bad", None), ({}, None), (-1, None), (0, None), ("2048", 2048)],
)
def test_invalid_capacity_values_do_not_create_negative_budgets(raw, expected):
    assert capacity._positive_int(raw) == expected


def test_unknown_provider_uses_bare_litellm_model(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "_LITELLM_CACHE",
        {"private-model": {"max_input_tokens": 32000, "max_output_tokens": 2048}},
    )
    result = capacity.suggest_capacity(
        "private-model", None, None, "llm", enabled=True, catalog={}
    )
    assert result.match_kind == CapacitySuggestionMatchKind.LITELLM_LOOKUP
    assert result.suggested_provider is None
    assert result.suggestions.context_window_tokens == 32000
    assert result.suggestions.max_output_tokens == 2048
    assert result.suggestions.max_input_tokens is None
    assert result.capacity_source_on_accept == "operator"


def test_final_segment_prefers_entry_with_both_limits(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "_LITELLM_CACHE",
        {
            "first/model": {"max_input_tokens": 1000},
            "second/MODEL": {"max_input_tokens": 64000, "max_output_tokens": 4096},
        },
    )
    result = capacity._litellm_lookup("organization/model", "unknown")
    assert result.suggestions.context_window_tokens == 64000
    assert result.suggestions.max_output_tokens == 4096
    assert result.canonical_model_name == "organization/model"


@pytest.mark.parametrize(
    "entry", [{}, {"max_input_tokens": "bad", "max_output_tokens": 0}, "invalid"]
)
def test_unusable_exact_entry_produces_no_suggestion(monkeypatch, entry):
    monkeypatch.setattr(capacity, "_LITELLM_CACHE", {"model": entry})
    assert capacity._litellm_lookup("model", None) is None


def test_repository_model_can_use_bare_final_segment(monkeypatch):
    monkeypatch.setattr(
        capacity, "_LITELLM_CACHE", {"model": {"max_output_tokens": 4096}}
    )
    result = capacity._litellm_lookup("org/model", "custom")
    assert result.suggestions.context_window_tokens is None
    assert result.suggestions.max_output_tokens == 4096


def test_optional_telemetry_failure_cannot_break_coverage(monkeypatch):
    counter = MagicMock()
    counter.add.side_effect = RuntimeError("meter closed")
    monkeypatch.setattr(capacity, "_capacity_suggestion_coverage_errors_total", counter)
    capacity._record_capacity_coverage_error(1, ValueError("invalid profile"))
    counter.add.assert_called_once()
