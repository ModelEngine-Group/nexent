import pytest

from backend.services.model_feature_configuration_service import (
    ModelFeatureConfigurationError,
    current_feature_baseline,
    enrich_feature_configuration,
    model_feature_identity,
    prepare_feature_override,
)


def _record(**updates):
    record = {
        "model_factory": "dashscope",
        "model_repo": "",
        "model_name": "qwen3.7-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "feature_capability_metadata": None,
        "feature_capability_override": None,
    }
    record.update(updates)
    return record


def test_p8_015_catalog_initializes_model_record_baseline():
    baseline = current_feature_baseline(_record())
    assert baseline["source"] == "catalog_family"
    assert baseline["reasoning"]["default_effort"] == "medium"


def test_p8_016_explicit_override_is_stamped_and_resolved():
    record = _record()
    override = prepare_feature_override(
        {"policy": {"reasoning": {"enabled": True, "effort": "low"}}},
        record,
    )
    assert override["authored_identity"] == model_feature_identity(record)
    enriched = enrich_feature_configuration(
        {**record, "feature_capability_override": override}
    )
    assert enriched["effective_feature_policy"]["reasoning"]["effort"] == "low"
    assert enriched["effective_feature_policy"]["source"] == "model_record_override"


def test_p8_016_invalid_override_fails_before_persistence():
    with pytest.raises(ModelFeatureConfigurationError, match="at least one effort"):
        prepare_feature_override(
            {
                "capability_patch": {
                    "reasoning": {
                        "mode": "effort",
                        "request_style": "openai_reasoning_effort",
                        "efforts": [],
                        "default_effort": None,
                    }
                }
            },
            _record(),
        )


def test_p8_017_identity_change_keeps_override_and_reports_warning():
    old_record = _record(model_name="old-model")
    override = prepare_feature_override(
        {
            "capability_patch": {
                "reasoning": {
                    "supported": True,
                    "mode": "toggle",
                    "request_style": "extra_body_enable_thinking",
                }
            }
        },
        old_record,
    )
    enriched = enrich_feature_configuration(
        _record(model_name="new-model", feature_capability_override=override)
    )
    assert enriched["feature_capability_override"] == override
    assert "override_identity_mismatch" in enriched["feature_capability_warnings"]


def test_p8_017_catalog_revision_refreshes_baseline_without_losing_override():
    record = _record(
        feature_capability_metadata={
            "schema_version": 1,
            "source": "catalog_family",
            "catalog_revision": "old",
            "reasoning": {"supported": False, "mode": "none", "request_style": "none"},
            "prompt_cache": {"supported": False, "mode": "none"},
        },
        feature_capability_override={
            "schema_version": 1,
            "policy": {"prompt_cache": {"enabled": False}},
        },
    )
    enriched = enrich_feature_configuration(record)
    assert enriched["feature_capability_baseline_changed"] is True
    assert enriched["feature_capability_override"] is not None
    assert enriched["effective_feature_policy"]["reasoning"]["enabled"] is True
    assert enriched["effective_feature_policy"]["prompt_cache"]["enabled"] is False


def test_p8_016_corrupt_database_override_fails_closed_for_reads():
    enriched = enrich_feature_configuration(
        _record(feature_capability_override={"policy": {"reasoning": {"enabled": "yes"}}})
    )
    assert enriched["effective_feature_policy"]["source"] == "nexent_default"
    assert enriched["feature_capability_warnings"] == [
        "invalid_feature_capability_override"
    ]
