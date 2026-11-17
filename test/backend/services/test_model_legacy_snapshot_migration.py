# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Historical envelopes import once, without changing canonical runtime storage."""

from copy import deepcopy
import json

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.model.adapter import restore_model_snapshot
from management.services.model.legacy_snapshot import model_source_fingerprint, restore_legacy_outlet_snapshot
from test.backend.services.model_profile_helpers import canonical_record, legacy_record


@pytest.fixture
def old():
    record = legacy_record()
    row = canonical_record(record)
    record["_legacy_outlet_snapshot"] = {"version": 1, "revision": row["config_revision"],
        "source_fingerprint": model_source_fingerprint(record), "row": row}
    # Credentials belong to the existing model row, not the encoded snapshot.
    record["_legacy_outlet_snapshot"]["row"].pop("api_key")
    return record


def test_frozen_snapshot_roundtrip_without_catalog_or_credentials(old, monkeypatch):
    before = deepcopy(old)
    monkeypatch.setattr("management.services.model.profiles.get_model_profile_catalog", lambda: pytest.fail("catalog"))
    profile = restore_legacy_outlet_snapshot(old)
    assert profile.outlet_id == 7 and profile.config_revision == 1
    assert profile.parameter_values["max_output_tokens"] == 256
    assert profile.parameter_values["temperature"] == .7
    assert profile.capabilities.tools.status == "supported"
    assert "unit-secret" not in json.dumps(old["_legacy_outlet_snapshot"])
    assert old == before


@pytest.mark.parametrize("changes", [{"base_url": "http://other/v1"}, {"temperature": .2}, {"api_key": ""}])
def test_stale_source_rejected_without_recomposition(old, changes):
    old.update(changes)
    with pytest.raises(ModelOutletValidationError) as error:
        restore_legacy_outlet_snapshot(old)
    assert error.value.category == "LEGACY_SNAPSHOT_STALE"


def test_key_rotation_and_status_do_not_change_policy_fingerprint(old):
    assert model_source_fingerprint(old) == model_source_fingerprint({**old, "api_key": "rotated", "connect_status": "available"})


@pytest.mark.parametrize("key,value", [("tenant_id", "other"), ("model_id", 9), ("config_revision", 8),
                                      ("model_name", "other"), ("base_url", "http://wrong/v1")])
def test_envelope_identity_and_revision_tampering_rejected(old, key, value):
    old["_legacy_outlet_snapshot"]["row"][key] = value
    with pytest.raises(ModelOutletValidationError):
        restore_legacy_outlet_snapshot(old)


@pytest.mark.parametrize("envelope", [{}, False, {"version": True}, {"version": 2}, {"version": 1, "padding": "x" * (1024 * 1024)}])
def test_invalid_envelope_is_not_treated_as_missing(old, envelope):
    old["_legacy_outlet_snapshot"] = envelope
    with pytest.raises(ModelOutletValidationError):
        restore_legacy_outlet_snapshot(old)


def test_corrupt_binding_fails_closed(old):
    old["_legacy_outlet_snapshot"]["row"]["protocol_id"] = "unregistered"
    with pytest.raises(ModelOutletValidationError) as error:
        restore_legacy_outlet_snapshot(old)
    assert error.value.category == "LEGACY_SNAPSHOT_INVALID"


def test_canonical_columns_supersede_bad_historical_envelope(old):
    record = canonical_record(legacy_record())
    record["_legacy_outlet_snapshot"] = {"version": 999}
    restored = restore_legacy_outlet_snapshot(record)
    assert restored.model_dump() == restore_model_snapshot(record, "tenant").model_dump()


def test_canonical_decode_failure_never_falls_back_to_envelope(old):
    record = canonical_record(legacy_record())
    record["_legacy_outlet_snapshot"] = old["_legacy_outlet_snapshot"]
    record["protocol_id"] = "unregistered"
    with pytest.raises(ValueError):
        restore_legacy_outlet_snapshot(record)


@pytest.mark.parametrize("extra", [{}, {"_legacy_outlet_snapshot": None}])
def test_missing_historical_data_uses_existing_legacy_migration(extra):
    assert restore_legacy_outlet_snapshot({**legacy_record(), **extra}) is None


def test_standard_runtime_rejects_other_tenant_and_ignores_transitional_data():
    record = canonical_record(legacy_record())
    record["runtime_outlet_snapshot"] = {"row": "invalid"}
    assert restore_model_snapshot(record, "tenant").outlet_id == 7
    with pytest.raises(ValueError):
        restore_model_snapshot(record, "other")


def test_removed_schema_and_runtime_dependencies():
    from pathlib import Path
    from management.db.model.models import ModelRecord
    root = Path(__file__).resolve().parents[3]
    assert "runtime_outlet_snapshot" not in ModelRecord.__table__.columns
    assert not (root / "deploy/sql/migrations/v2.7.2_1015_runtime_outlet_snapshot.sql").exists()
    for name in ("runtime_provisioning", "runtime_refresh", "runtime_snapshot"):
        assert not (root / f"backend/management/services/model/{name}.py").exists()


def test_import_retains_later_frozen_revision(old):
    old["_legacy_outlet_snapshot"]["revision"] = 7
    old["_legacy_outlet_snapshot"]["row"]["config_revision"] = 7
    assert restore_legacy_outlet_snapshot(old).config_revision == 7
