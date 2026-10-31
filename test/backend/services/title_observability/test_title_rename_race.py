# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Protect explicit conversation titles from delayed automatic generation."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("manual_title", ["User title", "New Conversation"])
async def test_delayed_generation_returns_preserved_manual_title(service, mocker, manual_title):
    initial = {"conversation_title": "New Conversation", "title_version": 0}
    current = dict(initial)
    mocker.patch.object(service, "get_conversation", side_effect=lambda *_a, **_k: dict(current))

    async def generate(*_args, **_kwargs):
        current.update(conversation_title=manual_title,
                       title_version=initial["title_version"] + 1)
        return "Automatic title"

    mocker.patch.object(service, "run_blocking", new=AsyncMock(side_effect=generate))

    def compare_and_set(_cid, title, _uid, *, expected_snapshot=None):
        if expected_snapshot and current != expected_snapshot:
            return False
        current["conversation_title"] = title
        return True

    save = mocker.patch.object(service, "rename_conversation", side_effect=compare_and_set)
    result = await service.generate_conversation_title_service(42, "Question", "user", "tenant")
    assert result == manual_title
    assert current["conversation_title"] == manual_title
    assert save.call_args.kwargs["expected_snapshot"] == initial


@pytest.mark.asyncio
async def test_unchanged_title_is_generated_with_an_owned_snapshot(service, mocker):
    snapshot = {"conversation_title": "New Conversation", "title_version": 0}
    read = mocker.patch.object(service, "get_conversation", return_value=snapshot)
    mocker.patch.object(service, "run_blocking", new=AsyncMock(return_value="Automatic title"))
    save = mocker.patch.object(service, "rename_conversation", return_value=True)
    assert await service.generate_conversation_title_service(42, "Question", "user", "tenant", model_id=7) == "Automatic title"
    read.assert_called_once_with(42, user_id="user", tenant_id="tenant")
    save.assert_called_once_with(42, "Automatic title", "user", expected_snapshot=snapshot)


@pytest.mark.asyncio
async def test_missing_owned_conversation_never_calls_model(service, mocker):
    mocker.patch.object(service, "get_conversation", return_value=None)
    mocker.patch.object(service, "rename_conversation", return_value=True)
    run = mocker.patch.object(service, "run_blocking", new=AsyncMock())
    with pytest.raises(service.ConversationNotFoundError):
        await service.generate_conversation_title_service(42, "Question", "user", "tenant")
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_conversation_during_generation_is_not_success(service, mocker):
    mocker.patch.object(service, "get_conversation", side_effect=[
        {"conversation_title": "New Conversation", "title_version": 0}, None,
    ])
    mocker.patch.object(service, "run_blocking", new=AsyncMock(return_value="Automatic title"))
    mocker.patch.object(service, "rename_conversation", return_value=False)
    with pytest.raises(service.ConversationNotFoundError):
        await service.generate_conversation_title_service(42, "Question", "user", "tenant")


@pytest.mark.parametrize("stored_title", ["User title", "New Conversation", "新对话"])
def test_automatic_fallback_only_renames_unchanged_default_titles(service, mocker, stored_title):
    snapshot = {"conversation_title": stored_title, "title_version": 0}
    mocker.patch.object(service, "get_conversation", return_value=snapshot)
    save = mocker.patch.object(service, "rename_conversation", return_value=True)
    result = service.rename_conversation_service(42, "Fallback", "user", only_if_default_title=True)
    assert result is (stored_title != "User title")
    if stored_title == "User title":
        save.assert_not_called()
    else:
        save.assert_called_once_with(42, "Fallback", "user", expected_snapshot=snapshot)


def test_racing_fallback_preserves_failed_compare_and_set(service, mocker):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0,
    })
    mocker.patch.object(service, "rename_conversation", return_value=False)
    assert service.rename_conversation_service(42, "Fallback", "user", only_if_default_title=True) is False


def test_generated_title_sql_atomically_checks_ownership_and_snapshot(service, mocker):
    import importlib

    db = importlib.import_module(service.rename_conversation.__module__)
    session = mocker.MagicMock()
    session.execute.return_value.rowcount = 1
    manager = mocker.patch.object(db, "get_db_session")
    manager.return_value.__enter__.return_value = session
    snapshot = {"conversation_title": "Initial", "title_version": 0}
    assert db.rename_conversation(42, "Generated", "user", expected_snapshot=snapshot) is True
    statement = session.execute.call_args.args[0]
    from sqlalchemy.dialects import postgresql

    sql = str(statement.compile(dialect=postgresql.dialect()))
    where = sql.split("WHERE", 1)[1]
    for column in ("conversation_id", "delete_flag", "created_by", "conversation_title", "title_version"):
        assert column in where
    params = statement.compile().params
    assert "Initial" in params.values()
    assert snapshot["title_version"] in params.values()
    assert "update_time" not in where
    assert "title_version=(nexent.conversation_record_t.title_version +" in sql
    assert "user" in params.values()
    session.execute.return_value.rowcount = 0
    assert db.rename_conversation(42, "Generated", "user", expected_snapshot=snapshot) is False


def test_manual_rename_keeps_unconditional_api_semantics(service, mocker):
    save = mocker.patch.object(service, "rename_conversation", return_value=True)
    assert service.rename_conversation_service(42, "User title", "user") is True
    save.assert_called_once_with(42, "User title", "user")


@pytest.mark.asyncio
async def test_activity_update_during_model_does_not_invalidate_title(service, mocker):
    initial = {"conversation_title": "New Conversation", "title_version": 0, "update_time": 10}
    current = dict(initial)
    mocker.patch.object(service, "get_conversation", side_effect=lambda *_a, **_k: dict(current))

    async def generate(*_args, **_kwargs):
        current["update_time"] = 20
        return "Automatic title"

    def compare_and_set(_cid, title, _uid, *, expected_snapshot):
        if any(current[key] != expected_snapshot.get(key) for key in ("conversation_title", "title_version")):
            return False
        current.update(conversation_title=title, title_version=current["title_version"] + 1)
        return True

    mocker.patch.object(service, "run_blocking", new=AsyncMock(side_effect=generate))
    save = mocker.patch.object(service, "rename_conversation", side_effect=compare_and_set)
    result = await service.generate_conversation_title_service(42, "Question", "user", "tenant")
    assert result == "Automatic title"
    assert current == {"conversation_title": "Automatic title", "title_version": 1, "update_time": 20}
    assert save.call_args.kwargs["expected_snapshot"] == {
        "conversation_title": "New Conversation", "title_version": 0,
    }


def test_unconditional_rename_atomically_advances_title_revision(service, mocker):
    import importlib
    from sqlalchemy.dialects import postgresql

    db = importlib.import_module(service.rename_conversation.__module__)
    session = mocker.MagicMock()
    session.execute.return_value.rowcount = 1
    manager = mocker.patch.object(db, "get_db_session")
    manager.return_value.__enter__.return_value = session
    assert db.rename_conversation(42, "Same title", "user") is True
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "title_version=(nexent.conversation_record_t.title_version +" in sql
    assert "title_version" not in sql.split("WHERE", 1)[1]
