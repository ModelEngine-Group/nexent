import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.as_dict = MagicMock(name="as_dict")
client_mod.filter_property = MagicMock(name="filter_property")
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod


db_models_mod = types.ModuleType("database.db_models")


class _ComparableColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return (self.name, "eq", other)

    def __lt__(self, other):
        return (self.name, "lt", other)


class ConversationShare:
    share_token = _ComparableColumn("share_token")
    conversation_id = _ComparableColumn("conversation_id")
    created_by = _ComparableColumn("created_by")
    delete_flag = _ComparableColumn("delete_flag")
    status = _ComparableColumn("status")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ConversationShareAsset:
    share_token = _ComparableColumn("asset_share_token")
    asset_id = _ComparableColumn("asset_id")
    delete_flag = _ComparableColumn("asset_delete_flag")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


db_models_mod.ConversationShare = ConversationShare
db_models_mod.ConversationShareAsset = ConversationShareAsset
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod


from backend.database import conversation_share_db as db


@pytest.fixture
def mock_session():
    session = MagicMock(name="session")

    @contextmanager
    def session_ctx():
        yield session

    return session, session_ctx


@pytest.fixture
def patch_session(monkeypatch, mock_session):
    session, session_ctx = mock_session
    monkeypatch.setattr(db, "get_db_session", session_ctx)
    return session


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

def _as_dict(record):
    return dict(record.__dict__)


def test_create_conversation_share_filters_and_sets_audit_fields(monkeypatch, patch_session):
    captured_payload = {}

    def filter_property(data, model_class):
        assert model_class is ConversationShare
        return {key: data[key] for key in ["share_token", "conversation_id", "title"] if key in data}

    def as_dict(record):
        captured_payload.update(record.__dict__)
        return _as_dict(record)

    monkeypatch.setattr(db, "filter_property", filter_property)
    monkeypatch.setattr(db, "as_dict", as_dict)

    result = db.create_conversation_share(
        {
            "share_token": "token-1",
            "conversation_id": 123,
            "title": "Shared conversation",
            "ignored": "drop-me",
        },
        user_id="user-1",
    )

    assert result["share_token"] == "token-1"
    assert result["created_by"] == "user-1"
    assert result["updated_by"] == "user-1"
    assert "ignored" not in result
    assert captured_payload == result
    patch_session.add.assert_called_once()
    patch_session.flush.assert_called_once()
    patch_session.refresh.assert_called_once()


def test_create_conversation_share_assets_returns_empty_without_session(monkeypatch):
    get_session = MagicMock()
    monkeypatch.setattr(db, "get_db_session", get_session)

    result = db.create_conversation_share_assets("token-1", [], user_id="user-1")

    assert result == []
    get_session.assert_not_called()


def test_create_conversation_share_assets_persists_each_asset(monkeypatch, patch_session):
    monkeypatch.setattr(
        db,
        "filter_property",
        lambda data, model_class: {
            key: data[key]
            for key in ["asset_id", "object_name", "filename"]
            if key in data
        },
    )
    monkeypatch.setattr(db, "as_dict", _as_dict)

    result = db.create_conversation_share_assets(
        "token-1",
        [
            {"asset_id": "asset-1", "object_name": "a.pdf", "filename": "a.pdf"},
            {"asset_id": "asset-2", "object_name": "b.pdf", "filename": "b.pdf"},
        ],
        user_id="user-1",
    )

    assert result == [
        {
            "asset_id": "asset-1",
            "object_name": "a.pdf",
            "filename": "a.pdf",
            "share_token": "token-1",
            "created_by": "user-1",
            "updated_by": "user-1",
        },
        {
            "asset_id": "asset-2",
            "object_name": "b.pdf",
            "filename": "b.pdf",
            "share_token": "token-1",
            "created_by": "user-1",
            "updated_by": "user-1",
        },
    ]
    assert patch_session.add.call_count == 2
    patch_session.flush.assert_called_once()
    assert patch_session.refresh.call_count == 2


def test_get_active_conversation_share_returns_record_when_not_expired(monkeypatch, patch_session):
    record = ConversationShare(
        share_token="token-1",
        status="active",
        expire_time=(datetime.now() + timedelta(hours=1)).isoformat(),
    )
    patch_session.scalars.return_value.first.return_value = record
    monkeypatch.setattr(db, "as_dict", _as_dict)

    result = db.get_active_conversation_share("token-1")

    assert result["share_token"] == "token-1"
    assert result["status"] == "active"
    patch_session.scalars.assert_called_once()


def test_get_active_conversation_share_returns_none_when_missing(patch_session):
    patch_session.scalars.return_value.first.return_value = None

    assert db.get_active_conversation_share("missing") is None


def test_get_active_conversation_share_returns_none_when_expired(monkeypatch, patch_session):
    record = ConversationShare(
        share_token="token-1",
        status="active",
        expire_time=datetime.now() - timedelta(seconds=1),
    )
    patch_session.scalars.return_value.first.return_value = record
    monkeypatch.setattr(db, "as_dict", _as_dict)

    assert db.get_active_conversation_share("token-1") is None


def test_get_share_asset_returns_none_when_missing(patch_session):
    patch_session.scalars.return_value.first.return_value = None

    assert db.get_share_asset("token-1", "missing") is None


def test_get_share_asset_returns_asset(monkeypatch, patch_session):
    record = ConversationShareAsset(
        share_token="token-1",
        asset_id="asset-1",
        object_name="attachments/a.pdf",
    )
    patch_session.scalars.return_value.first.return_value = record
    monkeypatch.setattr(db, "as_dict", _as_dict)

    result = db.get_share_asset("token-1", "asset-1")

    assert result["asset_id"] == "asset-1"
    assert result["object_name"] == "attachments/a.pdf"


def test_revoke_conversation_share_returns_true_when_row_updated(patch_session):
    patch_session.execute.return_value.rowcount = 1

    assert db.revoke_conversation_share("token-1", "user-1") is True
    patch_session.execute.assert_called_once()


def test_revoke_conversation_share_returns_false_when_no_row_updated(patch_session):
    patch_session.execute.return_value.rowcount = 0

    assert db.revoke_conversation_share("token-1", "user-1") is False
