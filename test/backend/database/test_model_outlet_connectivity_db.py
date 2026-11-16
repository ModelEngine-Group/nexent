# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tenant/revision query boundaries for connectivity status and credential presence."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from test.backend.database.test_model_outlet_db import database  # noqa: F401


@pytest.mark.parametrize("result,expected", [(True, True), (False, False), (None, False)])
def test_credential_flag_does_not_return_key_material(database, result, expected):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = result
    assert db.has_model_outlet_credential(12, "tenant-one", db_session=session) is expected
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "length(trim(nexent.model_record_t.api_key))" in sql
    assert "tenant_id" in sql and "delete_flag" in sql


def test_connectivity_status_is_revision_checked_without_config_write(database):
    db, _, errors = database
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = 12
    db.update_model_outlet_connectivity(12, "tenant-one", 3, "available", db_session=session)
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assignments = sql.split(" SET ")[1].split(" WHERE ")[0]
    assert assignments == "connect_status=%(connect_status)s, update_time=now()"
    assert "config_revision" in sql and "tenant_id" in sql and "model_type" in sql
    session.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(errors.ModelOutletConflictError):
        db.update_model_outlet_connectivity(12, "tenant-one", 3, "unavailable", db_session=session)


@pytest.mark.parametrize("revision,status", [(True, "available"), (0, "available"), (1, "detecting")])
def test_invalid_status_update_does_not_touch_database(database, revision, status):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.update_model_outlet_connectivity(12, "tenant-one", revision, status, db_session=MagicMock())
    assert client.sessions == []
