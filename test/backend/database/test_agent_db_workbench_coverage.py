from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test.backend.database import test_agent_db as legacy


agent_db = __import__("backend.database.agent_db", fromlist=["search_system_agent"])


def _session(monkeypatch, record):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = record

    @contextmanager
    def get_session():
        yield session

    monkeypatch.setattr(agent_db, "get_db_session", get_session)
    return session


@pytest.mark.parametrize("record", [None, SimpleNamespace(agent_id=17)])
def test_search_system_agent_returns_serialized_record_or_none(monkeypatch, record):
    _session(monkeypatch, record)
    monkeypatch.setattr(
        agent_db,
        "as_dict",
        MagicMock(return_value={"agent_id": 17, "system_key": "workbench_main"}),
    )

    result = agent_db.search_system_agent("tenant-a", "workbench_main", version_no=3)

    assert result == (
        {"agent_id": 17, "system_key": "workbench_main"} if record else None
    )


def test_update_system_agent_revision_updates_protected_draft(monkeypatch):
    record = SimpleNamespace(system_revision=None, updated_by=None)
    _session(monkeypatch, record)

    agent_db.update_system_agent_revision(
        agent_id=17,
        tenant_id="tenant-a",
        system_revision="2.5.3",
        user_id="system",
    )

    assert record.system_revision == "2.5.3"
    assert record.updated_by == "system"


def test_update_system_agent_revision_requires_existing_draft(monkeypatch):
    _session(monkeypatch, None)

    with pytest.raises(ValueError, match="System Agent draft not found"):
        agent_db.update_system_agent_revision(
            agent_id=17,
            tenant_id="tenant-a",
            system_revision="2.5.3",
            user_id="system",
        )


def test_update_agent_rejects_system_owned_record(monkeypatch):
    _session(monkeypatch, SimpleNamespace(agent_origin="SYSTEM"))

    with pytest.raises(ValueError, match="managed by the platform"):
        agent_db.update_agent(
            agent_id=17,
            agent_info=SimpleNamespace(),
            user_id="user-a",
        )


@pytest.mark.parametrize("record, expected", [(None, False), ((17,), True)])
def test_is_system_agent_checks_protected_identity(monkeypatch, record, expected):
    _session(monkeypatch, record)

    assert agent_db.is_system_agent(17, "tenant-a") is expected
