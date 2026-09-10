from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

class _ComparableColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return (self.name, "eq", other)

    def __add__(self, other):
        return (self.name, "add", other)


class FakeAgentShare:
    agent_share_id = _ComparableColumn("agent_share_id")
    public_share_id = _ComparableColumn("public_share_id")
    tenant_id = _ComparableColumn("tenant_id")
    agent_id = _ComparableColumn("agent_id")
    owner_user_id = _ComparableColumn("owner_user_id")
    token_generation = _ComparableColumn("token_generation")
    token_nonce = _ComparableColumn("token_nonce")
    status = _ComparableColumn("status")
    delete_flag = _ComparableColumn("delete_flag")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeAgentShareSession:
    agent_share_id = _ComparableColumn("session_agent_share_id")
    visitor_user_id = _ComparableColumn("visitor_user_id")
    conversation_id = _ComparableColumn("conversation_id")
    delete_flag = _ComparableColumn("session_delete_flag")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


from backend.database import agent_share_db as db


@pytest.fixture(autouse=True)
def patch_statement_builders(monkeypatch):
    class FakeStatement:
        def __init__(self, model_class):
            self.model_class = model_class
            self.conditions = ()
            self.updated_values = {}

        def where(self, *conditions):
            self.conditions = conditions
            return self

        def values(self, **values):
            self.updated_values = values
            return self

    monkeypatch.setattr(db, "select", lambda model_class: FakeStatement(model_class))
    monkeypatch.setattr(db, "update", lambda model_class: FakeStatement(model_class))
    monkeypatch.setattr(db, "AgentShare", FakeAgentShare)


@pytest.fixture
def session(monkeypatch):
    fake_session = MagicMock(name="session")

    @contextmanager
    def get_session():
        yield fake_session

    monkeypatch.setattr(db, "get_db_session", get_session)
    return fake_session


def test_create_agent_share_filters_payload_and_sets_manager_audit_fields(monkeypatch, session):
    monkeypatch.setattr(
        db,
        "filter_property",
        lambda data, model: {
            key: data[key]
            for key in ("public_share_id", "tenant_id", "agent_id", "owner_user_id", "token_nonce")
            if key in data
        },
    )
    monkeypatch.setattr(db, "as_dict", lambda record: dict(record.__dict__))

    result = db.create_agent_share(
        {
            "public_share_id": "f7e76518-4df2-4e10-9f49-48d785342f4f",
            "tenant_id": "tenant-1",
            "agent_id": 10,
            "owner_user_id": "owner-1",
            "token_nonce": "nonce-1",
            "untrusted": "discard-me",
        },
        manager_user_id="owner-1",
    )

    assert result["created_by"] == "owner-1"
    assert result["updated_by"] == "owner-1"
    assert result["status"] == "active"
    assert result["delete_flag"] == "N"
    assert "untrusted" not in result
    session.add.assert_called_once()
    session.flush.assert_called_once()
    session.refresh.assert_called_once()


def test_get_active_agent_share_scopes_the_lookup_to_tenant_and_agent(monkeypatch, session):
    share = FakeAgentShare(agent_share_id=1, tenant_id="tenant-1", agent_id=10)
    session.scalars.return_value.first.return_value = share
    monkeypatch.setattr(db, "as_dict", lambda record: dict(record.__dict__))

    result = db.get_active_agent_share("tenant-1", 10)

    assert result == {"agent_share_id": 1, "tenant_id": "tenant-1", "agent_id": 10}
    statement = session.scalars.call_args.args[0]
    assert statement.conditions == (
        ("tenant_id", "eq", "tenant-1"),
        ("agent_id", "eq", 10),
        ("status", "eq", "active"),
        ("delete_flag", "eq", "N"),
    )


def test_revoke_agent_share_is_scoped_to_its_manager(session):
    session.execute.return_value.rowcount = 1

    assert db.revoke_agent_share(3, "owner-1") is True
    statement = session.execute.call_args.args[0]
    assert statement.conditions == (
        ("agent_share_id", "eq", 3),
        ("owner_user_id", "eq", "owner-1"),
        ("status", "eq", "active"),
        ("delete_flag", "eq", "N"),
    )
    assert statement.updated_values == {"status": "revoked", "updated_by": "owner-1"}


def test_rotate_agent_share_increments_generation_and_replaces_nonce(session):
    session.execute.return_value.rowcount = 1

    assert db.rotate_agent_share(3, manager_user_id="owner-1", token_nonce="nonce-2") is True

    statement = session.execute.call_args.args[0]
    assert statement.conditions == (
        ("agent_share_id", "eq", 3),
        ("owner_user_id", "eq", "owner-1"),
        ("status", "eq", "active"),
        ("delete_flag", "eq", "N"),
    )
    assert statement.updated_values == {
        "token_generation": FakeAgentShare.token_generation + 1,
        "token_nonce": "nonce-2",
        "updated_by": "owner-1",
    }
