# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy views are derived from a saved row, never from a refreshed catalog."""

from copy import deepcopy

from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from management.services.model.outlet_projection import project_saved_outlet

from test.backend.services.test_model_outlet_migration_service import build, row


def test_projection_preserves_stored_format_and_exports_admin_review_information(monkeypatch):
    profile = build(row(extra_params={"enable_thinking": True, "__custom__": {"custom": {"flag": False}}}))
    stored = encode_resolved_model_profile(profile, registered_references=model_service_references())
    original = deepcopy(stored)
    monkeypatch.setattr("management.services.model.profiles.get_model_profile_catalog", lambda: (_ for _ in ()).throw(
        AssertionError("Saved projections must not reload TOML")))
    view = project_saved_outlet(stored)
    assert stored == original
    assert view["extra_params"] == {"enable_thinking": True, "__custom__": {"custom": {"flag": False}}}
    assert view["migration_status"] == "migrated" and view["migration_review_required"] is True
    assert view["migration_details"]["unmatched_atoms"] == ["model", "provider"]
    assert view["reasoning_capability"]["source"] == "operator"
    assert "api_key" not in view


def test_confirmed_revision_and_later_configuration_change_have_different_review_states():
    profile = build(row())
    data = profile.model_dump()
    data["provenance"]["provider_metadata"]["migration"]["reviewed_revision"] = 1
    profile = profile.__class__.model_validate(data)
    stored = encode_resolved_model_profile(profile, registered_references=model_service_references())
    assert project_saved_outlet(stored)["migration_review_required"] is False
    stored["config_revision"] = 2
    assert project_saved_outlet(stored)["migration_review_required"] is True


def test_failed_or_invalid_rows_report_diagnostic_without_legacy_guessing():
    assert project_saved_outlet({"profile_schema_version": None,
        "resolved_profile": {"migration_error": {"category": "LEGACY_OUTLET_INVALID"}}})["migration_status"] == "failed"
    assert project_saved_outlet({"profile_schema_version": 1})["migration_diagnostic"] == {
        "category": "PROFILE_STORAGE_INVALID"}
    assert project_saved_outlet({"model_type": "llm"}) is None
