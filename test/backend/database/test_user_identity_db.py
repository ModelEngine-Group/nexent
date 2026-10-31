# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the bounded identity query against controlled relational records."""

from contextlib import contextmanager
from unittest.mock import Mock

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, registry

from management.db.identity import user_identity as identity_db


def test_active_cas_bindings_only_and_no_writes(monkeypatch):
    metadata = MetaData()
    users = Table("users", metadata, Column("user_id", String, primary_key=True),
                  Column("user_email", String), Column("delete_flag", String))
    accounts = Table("accounts", metadata, Column("oauth_account_id", Integer, primary_key=True),
                     Column("user_id", String), Column("provider", String),
                     Column("provider_username", String), Column("delete_flag", String))
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(users.insert(), [
            {"user_id": key, "user_email": key + "@test", "delete_flag": "Y" if key == "deleted" else "N"}
            for key in ["a", "b", "blank", "local", "removed", "deleted", "unrequested"]
        ])
        connection.execute(accounts.insert(), [
            {"oauth_account_id": i, "user_id": key, "provider": provider,
             "provider_username": name, "delete_flag": flag}
            for i, (key, provider, name, flag) in enumerate([
                ("a", "cas", "  同名 ", "N"), ("a", "cas", "second", "N"),
                ("b", "cas", "同名", "N"), ("blank", "cas", " \t", "N"),
                ("local", "local", "local", "N"), ("removed", "cas", "removed", "Y"),
                ("deleted", "cas", "deleted", "N"), ("unrequested", "cas", "hidden", "N"),
            ], 1)
        ])
    mapper_registry = registry()
    user_model = type("User", (), {})
    account_model = type("Account", (), {})
    mapper_registry.map_imperatively(user_model, users)
    mapper_registry.map_imperatively(account_model, accounts)
    monkeypatch.setattr(identity_db, "UserTenant", user_model)
    monkeypatch.setattr(identity_db, "UserOAuthAccount", account_model)
    statements = []
    with Session(engine) as session:
        original_execute = session.execute

        def execute(statement):
            statements.append(statement)
            assert statement.is_select
            return original_execute(statement)

        monkeypatch.setattr(session, "execute", execute)

        @contextmanager
        def db_session():
            yield session

        monkeypatch.setattr(identity_db, "get_db_session", db_session)
        result = identity_db.get_cas_identities(["a", "a", "b", "blank", "local", "removed", "deleted", None])
    assert result == {
        "a": {"cas_username": "同名", "email": "a@test"},
        "b": {"cas_username": "同名", "email": "b@test"},
    }
    assert len(statements) == 1
    engine.dispose()


def test_empty_identity_ids_skip_database(monkeypatch):
    session = Mock()
    monkeypatch.setattr(identity_db, "get_db_session", session)
    assert identity_db.get_cas_identities([None, "", 42]) == {}
    session.assert_not_called()


def test_repository_associations_match_active_source_tenant_and_version(monkeypatch):
    metadata = MetaData()
    listings = Table("listings", metadata,
                     Column("agent_repository_id", Integer, primary_key=True),
                     Column("agent_id", Integer), Column("version_no", Integer),
                     Column("publisher_tenant_id", String), Column("publisher_user_id", String),
                     Column("delete_flag", String))
    agents = Table("agents", metadata, Column("id", Integer, primary_key=True),
                   Column("agent_id", Integer), Column("version_no", Integer),
                   Column("tenant_id", String), Column("created_by", String), Column("delete_flag", String))
    mapper_registry = registry()
    listing_model, agent_model = type("Listing", (), {}), type("Agent", (), {})
    mapper_registry.map_imperatively(listing_model, listings)
    mapper_registry.map_imperatively(agent_model, agents)
    monkeypatch.setattr(identity_db, "AgentRepository", listing_model)
    monkeypatch.setattr(identity_db, "AgentInfo", agent_model)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(listings.insert(), [
            {"agent_repository_id": i, "agent_id": i, "version_no": 2,
             "publisher_tenant_id": "t", "publisher_user_id": "publisher", "delete_flag": "Y" if i == 5 else "N"}
            for i in range(1, 7)
        ])
        connection.execute(agents.insert(), [
            {"id": i, "agent_id": i, "version_no": 1 if i == 2 else 2,
             "tenant_id": "other" if i == 3 else "t", "created_by": "creator", "delete_flag": "Y" if i == 4 else "N"}
            for i in range(1, 7)
        ])
    with Session(engine) as session:
        @contextmanager
        def db_session():
            yield session
        monkeypatch.setattr(identity_db, "get_db_session", db_session)
        result = identity_db.get_repository_agent_identity_ids([1, 2, 3, 4, 5])
    assert result[1] == {"author_id": "creator", "submitter_id": "publisher"}
    assert result[2] == result[3] == result[4] == {"author_id": None, "submitter_id": "publisher"}
    assert 5 not in result and 6 not in result
    engine.dispose()
