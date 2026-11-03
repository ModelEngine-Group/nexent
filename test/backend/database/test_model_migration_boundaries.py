# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Migration review and repair cannot confirm stale or cross-model snapshots."""

from unittest.mock import MagicMock, Mock

import pytest
from test.backend.database.model_outlet_helpers import REGISTRY, database, profile, row


@pytest.mark.parametrize("revision", [0, True, "1", 2**31])
def test_invalid_review_revision_never_opens_a_session(database, revision):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.confirm_model_outlet_migration(12, "tenant-one", "admin", revision, registered_references=REGISTRY)
    assert client.sessions == []


def test_missing_records_cannot_be_reviewed_or_repaired(database):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    assert db.confirm_model_outlet_migration(12, "tenant-one", "admin", 1,
        registered_references=REGISTRY, db_session=session) is None
    builder = Mock()
    with pytest.raises(LookupError, match="MODEL_OUTLET_NOT_FOUND"):
        db.repair_legacy_model_record(12, "tenant-one", "admin", 1, builder,
            registered_references=REGISTRY, db_session=session)
    builder.assert_not_called()
    assert session.execute.call_count == 2


@pytest.mark.parametrize("kind", ["embedding", "vlm"])
def test_repair_rejects_non_chat_rows_before_building(database, profile, kind):
    db, _, errors = database
    session = MagicMock()
    record = row(profile)
    record.update(profile_schema_version=None, model_type=kind)
    session.execute.return_value.mappings.return_value.first.return_value = record
    builder = Mock()
    with pytest.raises(errors.ModelOutletValidationError):
        db.repair_legacy_model_record(12, "tenant-one", "admin", 1, builder,
            registered_references=REGISTRY, db_session=session)
    builder.assert_not_called()
    assert session.execute.call_count == 1


def test_repair_builder_cannot_replace_the_row_identity(database, profile):
    db, _, errors = database
    session = MagicMock()
    record = row(profile)
    record["profile_schema_version"] = None
    session.execute.return_value.mappings.return_value.first.return_value = record
    builder = Mock(return_value=(profile.model_copy(update={"outlet_id": 99}), None))
    with pytest.raises(errors.ModelOutletValidationError):
        db.repair_legacy_model_record(12, "tenant-one", "admin", 1, builder,
            registered_references=REGISTRY, db_session=session)
    assert session.execute.call_count == 1
    session.commit.assert_not_called()


def test_review_cas_failure_does_not_claim_confirmation(database, profile):
    db, _, errors = database
    data = profile.model_dump()
    data["provenance"]["provider_metadata"]["migration"] = {"reviewed_revision": None}
    migrated = profile.__class__.model_validate(data)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(migrated)
    session.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(errors.ModelOutletConflictError):
        db.confirm_model_outlet_migration(12, "tenant-one", "admin", 1,
            registered_references=REGISTRY, db_session=session)
    assert session.execute.call_count == 2
    session.commit.assert_not_called()


def test_dry_run_reports_builder_identity_mismatch_without_writes(database, profile):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [row(profile)]
    result = db.migrate_legacy_model_records(Mock(return_value=profile.model_copy(update={"outlet_id": 99})),
        registered_references=REGISTRY, dry_run=True, db_session=session)
    assert result[0]["status"] == "failed"
    assert result[0]["category"] == "LEGACY_MIGRATION_IDENTITY_INVALID"
    assert session.execute.call_count == 1
