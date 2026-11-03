# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Migration transaction scope, exclusions, dry runs and safe failure persistence."""

from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from test.backend.database.test_model_outlet_db import database, profile, REGISTRY, row  # noqa: F401


def test_batch_locks_legacy_rows_preserves_credentials_and_references(database, profile):
    db, client, _ = database
    session = MagicMock()
    legacy = row(profile)
    legacy.update(profile_schema_version=None, api_key="controlled-key", delete_flag="Y")
    session.execute.return_value.mappings.return_value.all.return_value = [legacy]
    result = db.migrate_legacy_model_records(Mock(return_value=profile), registered_references=REGISTRY, db_session=session)
    assert result == [{"model_id": 12, "tenant_id": "tenant-one", "status": "migrated", "category": None}]
    read, write = [call.args[0] for call in session.execute.call_args_list]
    sql = str(read.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "profile_schema_version IS NULL" in sql and "model_type IN" in sql
    assert "delete_flag" not in sql.split("WHERE ", 1)[1]
    values = write.compile().params
    assert "api_key" not in values and "delete_flag" not in values and "model_id" not in values
    assert values["max_tokens"] is None and values["model_repo"] is None
    session.commit.assert_not_called()
    assert client.sessions == [session]


def test_dry_run_does_not_lock_or_write(database, profile):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [row(profile)]
    result = db.migrate_legacy_model_records(Mock(return_value=profile), registered_references=REGISTRY,
        dry_run=True, db_session=session)
    assert result[0]["status"] == "ready"
    assert session.execute.call_count == 1
    assert "FOR UPDATE" not in str(session.execute.call_args.args[0])


def test_failure_keeps_old_values_and_persists_only_sanitized_diagnostic(database):
    db, _, errors = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [{"model_id": 12, "tenant_id": "tenant-one"}]
    builder = Mock(side_effect=errors.ModelOutletValidationError(category="LEGACY_OUTLET_INVALID", path="base_url"))
    result = db.migrate_legacy_model_records(builder, registered_references=REGISTRY, db_session=session)
    assert result[0]["status"] == "failed"
    values = session.execute.call_args_list[1].args[0].compile().params
    assert values["resolved_profile"] == {"migration_error": {"category": "LEGACY_OUTLET_INVALID", "field": "base_url"}}
    assert "extra_params" not in values and "api_key" not in values and "profile_schema_version" not in values


@pytest.mark.parametrize("options", [{"batch_size": 0}, {"batch_size": True}, {"after_model_id": -1}])
def test_invalid_batch_bounds_never_open_database(database, options):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.migrate_legacy_model_records(Mock(), registered_references=REGISTRY, **options)
    assert client.sessions == []


def test_review_updates_only_provenance_at_the_locked_revision(database, profile):
    db, _, _ = database
    data = profile.model_dump()
    data["provenance"]["provider_metadata"]["migration"] = {"reviewed_revision": None, "version": "fixture_v1"}
    profile = profile.__class__.model_validate(data)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    session.execute.return_value.scalar_one_or_none.return_value = 12
    result = db.confirm_model_outlet_migration(12, "tenant-one", "admin", 1,
        registered_references=REGISTRY, db_session=session)
    assert result["config_revision"] == 1 and result["migration_review_required"] is False
    write = session.execute.call_args_list[1].args[0]
    values = write.compile().params
    migration = values["resolved_profile"]["provenance"]["provider_metadata"]["migration"]
    assert migration["reviewed_revision"] == 1 and migration["reviewed_by"] == "admin"
    assert "api_key" not in values and "extra_params" not in values and "config_revision" not in values
    session.commit.assert_not_called()


def test_stale_or_non_migration_review_never_writes(database, profile):
    db, _, errors = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    with pytest.raises(errors.ModelOutletConflictError):
        db.confirm_model_outlet_migration(12, "tenant-one", "admin", 2,
            registered_references=REGISTRY, db_session=session)
    assert session.execute.call_count == 1
    session.reset_mock()
    with pytest.raises(errors.ModelOutletValidationError):
        db.confirm_model_outlet_migration(12, "tenant-one", "admin", 1,
            registered_references=REGISTRY, db_session=session)
    assert session.execute.call_count == 1


def test_repair_keeps_id_credential_and_uses_a_locked_row(database, profile):
    db, _, _ = database
    session = MagicMock()
    old = row(profile)
    old["profile_schema_version"] = None
    session.execute.return_value.mappings.return_value.first.return_value = old
    result = db.repair_legacy_model_record(12, "tenant-one", "admin", 1, Mock(return_value=(profile, None)),
        registered_references=REGISTRY, db_session=session)
    assert result == {"model_id": 12, "config_revision": 2}
    assert "FOR UPDATE" in str(session.execute.call_args_list[0].args[0])
    values = session.execute.call_args_list[1].args[0].compile().params
    assert values["config_revision"] == 2 and values["api_key"] is None
    assert values["profile_schema_version"] == 1 and values["max_tokens"] is None
    assert "model_id" not in values and "tenant_id" not in values and "delete_flag" not in values
    session.commit.assert_not_called()


@pytest.mark.parametrize("ready,version", [(False, 2), (True, 1)])
def test_repair_cannot_overwrite_a_newer_or_already_migrated_row(database, profile, ready, version):
    db, _, errors = database
    session = MagicMock()
    old = row(profile)
    old["profile_schema_version"] = 1 if ready else None
    session.execute.return_value.mappings.return_value.first.return_value = old
    builder = Mock()
    with pytest.raises(errors.ModelOutletConflictError):
        db.repair_legacy_model_record(12, "tenant-one", "admin", version, builder,
            registered_references=REGISTRY, db_session=session)
    builder.assert_not_called()
    assert session.execute.call_count == 1
