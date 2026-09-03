import os
import sys

import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from consts.exceptions import ModelCapacityConfigError
from services.model_capacity_governance_service import (
    apply_catalog_adoption,
    catalog_adoption_preview,
    derive_legacy_metadata,
    merge_capacity_governance,
    normalize_legacy_capacity_ingress,
)


CATALOG_VALUES = {
    "context_window_tokens": 128_000,
    "max_output_tokens": 16_384,
    "default_output_reserve_tokens": 4_096,
    "tokenizer_family": "o200k_base",
}


def catalog_row():
    result = merge_capacity_governance(
        {"model_type": "llm", **CATALOG_VALUES},
        explicit_fields={"model_type", *CATALOG_VALUES},
        accepted_profile_version="openai/gpt-4o@2",
        accepted_profile_fields=CATALOG_VALUES,
        profile_evidence_id="openai-model-doc",
        profile_verified_at="2026-08-01T00:00:00Z",
    )
    return {
        **result.values,
        "capacity_field_metadata": result.metadata,
        "capacity_source": result.row_capacity_source,
        "capability_profile_version": result.capability_profile_version,
    }


def test_ac_p1_001_catalog_create_tracks_each_field():
    row = catalog_row()

    assert row["capacity_source"] == "profile"
    assert row["capability_profile_version"] == "openai/gpt-4o@2"
    assert set(row["capacity_field_metadata"]["fields"]) == set(CATALOG_VALUES)
    assert all(
        item["source"] == "catalog"
        for item in row["capacity_field_metadata"]["fields"].values()
    )


def test_ac_p1_001_only_changed_field_becomes_operator():
    existing = catalog_row()
    result = merge_capacity_governance(
        {"max_output_tokens": 8_192, "context_window_tokens": 128_000},
        explicit_fields={"max_output_tokens", "context_window_tokens"},
        existing=existing,
    )

    assert result.metadata["fields"]["max_output_tokens"]["source"] == "operator"
    assert result.metadata["fields"]["context_window_tokens"]["source"] == "catalog"
    assert result.metadata["fields"]["tokenizer_family"]["source"] == "catalog"
    assert result.row_capacity_source == "operator"
    assert result.capability_profile_version == "openai/gpt-4o@2"
    assert [item["field"] for item in result.audit_delta] == ["max_output_tokens"]


def test_ac_p1_001_omitted_fields_and_equal_echo_preserve_metadata():
    existing = catalog_row()
    result = merge_capacity_governance(
        {"context_window_tokens": 128_000, "base_url": "https://new.example/v1"},
        explicit_fields={"context_window_tokens", "base_url"},
        existing=existing,
    )

    assert result.metadata == existing["capacity_field_metadata"]
    assert result.audit_delta == ()


def test_ac_p5_003_provider_wins_catalog_but_not_operator():
    existing = catalog_row()
    existing["max_output_tokens"] = 8_192
    existing["capacity_field_metadata"]["fields"]["max_output_tokens"] = {
        "source": "operator"
    }
    result = merge_capacity_governance(
        {
            "context_window_tokens": 262_144,
            "max_output_tokens": 65_536,
        },
        explicit_fields={"context_window_tokens", "max_output_tokens"},
        existing=existing,
        accepted_profile_version="silicon/qwen3.6-27b@2",
        accepted_profile_fields={"context_window_tokens", "max_output_tokens"},
        provider_fields={"context_window_tokens", "max_output_tokens"},
    )

    assert result.values["context_window_tokens"] == 262_144
    assert result.metadata["fields"]["context_window_tokens"]["source"] == "provider"
    assert result.values["max_output_tokens"] == 8_192
    assert result.metadata["fields"]["max_output_tokens"]["source"] == "operator"
    assert result.row_capacity_source == "operator"


def test_ac_p5_003_provider_capacity_ignores_legacy_generation_default():
    normalized, explicit, used_legacy = normalize_legacy_capacity_ingress(
        {
            "model_type": "llm",
            "capacity_source": "provider_candidate",
            "max_tokens": 4_096,
            "max_output_tokens": 131_072,
        },
        explicit_fields={"max_tokens", "max_output_tokens"},
    )

    assert normalized["max_output_tokens"] == 131_072
    assert "max_tokens" not in normalized
    assert explicit == {"max_output_tokens"}
    assert used_legacy is False


def test_ac_p5_003_equal_provider_value_replaces_catalog_provenance():
    existing = catalog_row()
    result = merge_capacity_governance(
        {"context_window_tokens": existing["context_window_tokens"]},
        explicit_fields={"context_window_tokens"},
        existing=existing,
        provider_fields={"context_window_tokens"},
    )

    assert result.values["context_window_tokens"] == existing["context_window_tokens"]
    assert result.metadata["fields"]["context_window_tokens"]["source"] == "provider"
    assert result.audit_delta == (
        {
            "field": "context_window_tokens",
            "previous_source": "catalog",
            "new_source": "provider",
            "value_changed": False,
        },
    )


def test_ac_p1_002_explicit_clear_becomes_unknown_without_fabrication():
    existing = catalog_row()
    result = merge_capacity_governance(
        {"max_input_tokens": None},
        explicit_fields={"max_input_tokens"},
        existing=existing,
    )

    assert result.values["max_input_tokens"] is None
    assert "max_input_tokens" not in result.metadata["fields"]


def test_ac_p1_010_lone_legacy_max_tokens_normalizes_once():
    payload, explicit, used_legacy = normalize_legacy_capacity_ingress(
        {"model_type": "llm", "max_tokens": 4096},
        explicit_fields={"model_type", "max_tokens"},
    )
    result = merge_capacity_governance(
        payload,
        explicit_fields=explicit,
        legacy_ingress_used=used_legacy,
    )

    assert payload["max_output_tokens"] == 4096
    assert "max_tokens" not in payload
    assert result.metadata["fields"]["max_output_tokens"]["source"] == "legacy"


def test_ac_p1_010_conflicting_dual_legacy_values_rejected():
    with pytest.raises(ModelCapacityConfigError) as exc_info:
        normalize_legacy_capacity_ingress(
            {"model_type": "llm", "max_tokens": 4096, "max_output_tokens": 8192},
            explicit_fields={"model_type", "max_tokens", "max_output_tokens"},
        )

    assert exc_info.value.reason_code == "capacity_legacy_conflict"


def test_ac_p1_010_embedding_max_tokens_is_not_capacity_alias():
    payload, explicit, used_legacy = normalize_legacy_capacity_ingress(
        {"model_type": "embedding", "max_tokens": 1024},
        explicit_fields={"model_type", "max_tokens"},
    )

    assert payload["max_tokens"] == 1024
    assert explicit == {"model_type", "max_tokens"}
    assert not used_legacy


def test_ac_p1_009_catalog_preview_is_side_effect_free_and_blocks_manual():
    record = catalog_row()
    overridden = merge_capacity_governance(
        {"max_output_tokens": 8192},
        explicit_fields={"max_output_tokens"},
        existing=record,
    )
    record.update(overridden.values)
    record["capacity_field_metadata"] = overridden.metadata
    before = dict(record)

    preview = catalog_adoption_preview(
        record,
        {"context_window_tokens": 256_000, "max_output_tokens": 32_768},
        proposed_profile_version="openai/gpt-4o@3",
    )

    assert preview["fields"]["context_window_tokens"]["applicable"]
    assert preview["fields"]["max_output_tokens"]["blocked_by_manual"]
    assert not preview["fields"]["max_output_tokens"]["applicable"]
    assert record == before


def test_ac_p1_002_legacy_metadata_is_derived_without_mutation():
    record = {
        "context_window_tokens": 32_768,
        "max_output_tokens": 4096,
        "capacity_source": "operator",
    }
    before = dict(record)

    metadata = derive_legacy_metadata(record)

    assert metadata["fields"]["context_window_tokens"]["source"] == "operator"
    assert record == before


def test_ac_p1_009_default_adoption_updates_catalog_and_preserves_manual():
    record = catalog_row()
    overridden = merge_capacity_governance(
        {"max_output_tokens": 8192},
        explicit_fields={"max_output_tokens"},
        existing=record,
    )
    record.update(overridden.values)
    record["capacity_field_metadata"] = overridden.metadata

    adopted = apply_catalog_adoption(
        record,
        {"context_window_tokens": 256_000, "max_output_tokens": 32_768},
        proposed_profile_version="openai/gpt-4o@3",
        expected_profile_version="openai/gpt-4o@3",
        current_matcher_version="1.0.0",
        expected_matcher_version="1.0.0",
    )
    assert adopted.values["context_window_tokens"] == 256_000
    assert adopted.values["max_output_tokens"] == 8192
    assert adopted.metadata["fields"]["context_window_tokens"]["source"] == "catalog"
    assert adopted.metadata["fields"]["max_output_tokens"]["source"] == "operator"


def test_ac_p1_009_manual_reset_requires_explicit_field_and_is_audited():
    record = catalog_row()
    overridden = merge_capacity_governance(
        {"max_output_tokens": 8192},
        explicit_fields={"max_output_tokens"},
        existing=record,
    )
    record.update(overridden.values)
    record["capacity_field_metadata"] = overridden.metadata
    adopted = apply_catalog_adoption(
        record,
        {"max_output_tokens": 32_768},
        proposed_profile_version="openai/gpt-4o@3",
        expected_profile_version="openai/gpt-4o@3",
        current_matcher_version="1.0.0",
        fields={"max_output_tokens"},
        reset_manual_fields={"max_output_tokens"},
    )
    assert adopted.values["max_output_tokens"] == 32_768
    assert adopted.metadata["fields"]["max_output_tokens"]["source"] == "catalog"
    assert adopted.audit_delta[0]["previous_source"] == "operator"


def test_ac_p1_009_manual_reset_changes_provenance_when_value_is_identical():
    record = catalog_row()
    overridden = merge_capacity_governance(
        {"max_output_tokens": 32_768},
        explicit_fields={"max_output_tokens"},
        existing=record,
    )
    record.update(overridden.values)
    record["capacity_field_metadata"] = overridden.metadata

    adopted = apply_catalog_adoption(
        record,
        {"max_output_tokens": 32_768},
        proposed_profile_version="openai/gpt-4o@3",
        expected_profile_version="openai/gpt-4o@3",
        current_matcher_version="1.0.0",
        fields={"max_output_tokens"},
        reset_manual_fields={"max_output_tokens"},
    )

    assert adopted.values["max_output_tokens"] == 32_768
    assert adopted.metadata["fields"]["max_output_tokens"]["source"] == "catalog"
    assert adopted.audit_delta == (
        {
            "field": "max_output_tokens",
            "previous_source": "operator",
            "new_source": "catalog",
            "value_changed": False,
        },
    )


def test_ac_p3_002_reviewed_legacy_adoption_changes_same_value_provenance():
    record = {
        "model_type": "llm",
        **CATALOG_VALUES,
        "capacity_source": "legacy",
    }
    preview = catalog_adoption_preview(
        record,
        CATALOG_VALUES,
        proposed_profile_version="openai/gpt-4o@2",
    )

    assert all(item["applicable"] for item in preview["fields"].values())
    adopted = apply_catalog_adoption(
        record,
        CATALOG_VALUES,
        proposed_profile_version="openai/gpt-4o@2",
        expected_profile_version="openai/gpt-4o@2",
        current_matcher_version="1.0.0",
    )

    assert adopted.row_capacity_source == "profile"
    assert adopted.capability_profile_version == "openai/gpt-4o@2"
    assert all(
        item["source"] == "catalog"
        for item in adopted.metadata["fields"].values()
    )
    assert {item["field"] for item in adopted.audit_delta} == set(CATALOG_VALUES)
    assert all(not item["value_changed"] for item in adopted.audit_delta)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"expected_profile_version": "old"}, "capacity_profile_stale"),
        ({"expected_matcher_version": "old"}, "capacity_matcher_stale"),
    ],
)
def test_ac_p1_009_stale_adoption_is_rejected(kwargs, reason):
    arguments = {
        "proposed_profile_version": "openai/gpt-4o@3",
        "expected_profile_version": "openai/gpt-4o@3",
        "current_matcher_version": "1.0.0",
        "expected_matcher_version": "1.0.0",
    }
    arguments.update(kwargs)
    with pytest.raises(ModelCapacityConfigError) as exc_info:
        apply_catalog_adoption(
            catalog_row(),
            {"context_window_tokens": 256_000},
            **arguments,
        )
    assert exc_info.value.reason_code == reason
