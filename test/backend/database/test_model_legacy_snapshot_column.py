# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Optional historical columns are read exclusively by explicit migrations."""

from unittest.mock import MagicMock, Mock

import pytest
from test.backend.database.test_model_outlet_db import database, profile, REGISTRY, row  # noqa: F401


@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_explicit_migration_reads_old_column_only_when_present(database, profile, monkeypatch, exists, dry_run):
    db, _, _ = database
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": "runtime_outlet_snapshot"}] if exists else []
    monkeypatch.setattr(db, "inspect", Mock(return_value=inspector))
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [row(profile)]
    result = db.migrate_legacy_model_records(Mock(return_value=profile), registered_references=REGISTRY,
        db_session=session, dry_run=dry_run, include_legacy_snapshot=True)
    sql = str(session.execute.call_args_list[0].args[0])
    assert ("runtime_outlet_snapshot" in sql) is exists
    assert ("_legacy_outlet_snapshot" in sql) is exists
    assert result[0]["status"] == ("ready" if dry_run else "migrated")
    if not dry_run:
        assert "runtime_outlet_snapshot" not in str(session.execute.call_args_list[1].args[0])
    assert session.execute.call_count == (1 if dry_run else 2)
    session.commit.assert_not_called()


def test_default_storage_never_probes_or_selects_removed_column(database, profile, monkeypatch):
    db, _, _ = database
    probe = Mock(side_effect=AssertionError("Unexpected schema dependency"))
    monkeypatch.setattr(db, "inspect", probe)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [row(profile)]
    db.migrate_legacy_model_records(Mock(return_value=profile), registered_references=REGISTRY,
        db_session=session, dry_run=True)
    assert "runtime_outlet_snapshot" not in str(session.execute.call_args.args[0])
    probe.assert_not_called()
