from __future__ import annotations

import pytest

from consts.exceptions import ModelCapacityConfigError
from services.model_capacity_validation_service import (
    audit_capacity_records,
    validate_capacity_contract,
)


def _llm(**overrides):
    row = {
        "model_id": 1,
        "model_name": "test-model",
        "model_type": "llm",
        "context_window_tokens": 32_768,
        "max_input_tokens": None,
        "max_output_tokens": 4_096,
        "default_output_reserve_tokens": 1_024,
        "capacity_source": "operator",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"context_window_tokens": 0}, "non_positive_or_non_integer"),
        ({"max_output_tokens": 32_768}, "max_output_not_below_context"),
        ({"max_input_tokens": 40_000}, "max_input_exceeds_context"),
        (
            {"default_output_reserve_tokens": 8_192},
            "default_output_exceeds_max_output",
        ),
    ],
)
def test_ac_004_invalid_contracts_return_stable_reasons(overrides, reason):
    with pytest.raises(ModelCapacityConfigError) as exc_info:
        validate_capacity_contract(_llm(**overrides))

    assert exc_info.value.reason_code == f"capacity_config_invalid.{reason}"


def test_ac_004_partial_update_validates_merged_effective_row():
    with pytest.raises(ModelCapacityConfigError) as exc_info:
        validate_capacity_contract(
            {"max_output_tokens": 40_000}, existing=_llm()
        )

    assert exc_info.value.reason_code.endswith("max_output_not_below_context")


def test_ac_005_unknown_capacity_is_preserved_as_valid_migration_state():
    contract = validate_capacity_contract(
        _llm(
            context_window_tokens=None,
            max_input_tokens=None,
            max_output_tokens=None,
            default_output_reserve_tokens=None,
            capacity_source=None,
        )
    )

    assert contract["context_window_tokens"] is None
    assert contract["capacity_source"] is None


def test_ac_008_audit_is_sanitized_and_does_not_mutate_rows():
    records = [
        _llm(),
        _llm(model_id=2, context_window_tokens=None, max_output_tokens=None),
        _llm(model_id=3, default_output_reserve_tokens=None),
        _llm(model_id=4, max_output_tokens=32_768),
    ]
    original = [dict(row) for row in records]

    report = audit_capacity_records(records)

    assert records == original
    assert report["counts"] == {
        "suspicious": 2,
        "unknown": 1,
        "invalid": 1,
    }
    assert all("api_key" not in row for row in report["rows"])
    assert report["rows"][2]["reasons"] == ["operator_shaped_ui_default"]
