# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for shared system configuration persistence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def _repository():
    from management.configuration.repository import SystemConfigurationRepository

    return SystemConfigurationRepository()


def _validation_error():
    from management.configuration.catalog import ConfigurationValidationError

    return ConfigurationValidationError


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.commit = Mock()
        self.rollback = Mock()
        self.close = Mock()

    def scalars(self, _statement):
        return _ScalarResult(self.rows)

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))


def _rows(values=None):
    return [
        SimpleNamespace(
            configuration_id=index + 1,
            configuration_key=key,
            configuration_value=value,
        )
        for index, (key, value) in enumerate((values or EXPECTED_DEFAULTS).items())
    ]


def test_load_snapshot_returns_domain_values_not_orm_rows():
    snapshot = _repository().load_snapshot(_Session(_rows()))

    assert snapshot.to_dict() == EXPECTED_DEFAULTS
    assert not hasattr(snapshot, "configuration_key")


def test_load_snapshot_rejects_missing_and_duplicate_active_keys():
    missing = _rows()[:-1]
    with pytest.raises(_validation_error()):
        _repository().load_snapshot(_Session(missing))

    duplicated = _rows() + _rows({"MAX_TENANT_COUNT": 5})
    with pytest.raises(_validation_error(), match="MAX_TENANT_COUNT"):
        _repository().load_snapshot(_Session(duplicated))


def test_consumer_snapshot_uses_the_read_only_database_role():
    session = _Session(_rows())

    _repository().load_snapshot(session, read_only=True)

    assert "SET LOCAL ROLE nexent_configuration_reader" in session.statements[0][0]


def test_save_changes_locks_and_updates_only_changed_keys():
    session = _Session(_rows())

    snapshot = _repository().save_changes(
        session,
        {"MAX_TENANT_COUNT": 5, "MAX_USERS_PER_TENANT": 10000},
        actor="ops-user",
    )

    assert snapshot.get("MAX_TENANT_COUNT") == 5
    assert snapshot.get("MAX_USERS_PER_TENANT") == 10000
    assert "pg_advisory_xact_lock" in session.statements[0][0]
    updates = [item for item in session.statements if "UPDATE" in item[0].upper()]
    assert len(updates) == 1
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


def test_invalid_batch_performs_no_updates():
    session = _Session(_rows())

    with pytest.raises(_validation_error()):
        _repository().save_changes(
            session,
            {"MAX_TENANT_COUNT": 5, "MAX_USERS_PER_TENANT": 0},
            actor="ops-user",
        )

    assert not [item for item in session.statements if "UPDATE" in item[0].upper()]
    session.rollback.assert_not_called()
