"""Tests for the guarded NL2AGENT cutover cleanup script."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.scripts import cleanup_nl2agent_cutover as cleanup
from utils.nl2agent_catalog_snapshot import create_catalog_snapshot


_CATALOG_SNAPSHOT = create_catalog_snapshot(
    {
        "tool_catalog": [],
        "skill_catalog": [],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    },
    catalog_version="catalog_11111111111111111111111111111111",
)


def _legacy_session(session_id=4, conversation_id=12):
    return {
        "session_id": session_id,
        "conversation_id": conversation_id,
        "draft_agent_id": 202,
        "status": "active",
        "workflow_schema_version": 2,
        "session_catalogs": {},
        "workflow_state": {
            "schema_version": 2,
            "card_delivery": {},
            "online_installations": {},
        },
    }


def _healthy_session():
    return {
        "session_id": 4,
        "conversation_id": 12,
        "draft_agent_id": 202,
        "status": "active",
        "workflow_schema_version": 3,
        "session_catalogs": _CATALOG_SNAPSHOT,
        "workflow_state": {"schema_version": 3},
    }


def _builder_conversation(conversation_id=12):
    return {
        "conversation_id": conversation_id,
        "conversation_title": "NL2AGENT - draft_12345678",
        "agent_id": 101,
        "agent_name": "nl2agent",
    }


def test_validate_cleanup_targets_accepts_exact_legacy_mapping():
    targets = cleanup.validate_cleanup_targets(
        [_legacy_session()],
        [_builder_conversation()],
        expected_session_ids=[4],
        expected_conversation_ids=[12],
    )

    assert targets == [
        cleanup.CleanupTarget(
            session_id=4,
            conversation_id=12,
            draft_agent_id=202,
            status="active",
            workflow_schema_version=2,
            reasons=(
                "active_schema_mismatch",
                "legacy_schema",
                "legacy_workflow_state",
            ),
        )
    ]


def test_validate_cleanup_targets_rejects_changed_mapping():
    with pytest.raises(cleanup.CutoverCleanupError, match="not bound to the exact"):
        cleanup.validate_cleanup_targets(
            [_legacy_session(conversation_id=13)],
            [_builder_conversation(conversation_id=12)],
            expected_session_ids=[4],
            expected_conversation_ids=[12],
        )


def test_validate_cleanup_targets_rejects_healthy_v3_session():
    with pytest.raises(cleanup.CutoverCleanupError, match="healthy v3 Session"):
        cleanup.validate_cleanup_targets(
            [_healthy_session()],
            [_builder_conversation()],
            expected_session_ids=[4],
            expected_conversation_ids=[12],
        )


def test_validate_cleanup_targets_rejects_non_builder_conversation():
    conversation = {
        **_builder_conversation(),
        "conversation_title": "User conversation",
        "agent_name": "ordinary-agent",
    }
    with pytest.raises(cleanup.CutoverCleanupError, match="not an internal"):
        cleanup.validate_cleanup_targets(
            [_legacy_session()],
            [conversation],
            expected_session_ids=[4],
            expected_conversation_ids=[12],
        )


def test_soft_delete_updates_only_cutover_graph_roots():
    db_session = MagicMock()
    db_session.execute.side_effect = [
        SimpleNamespace(rowcount=count) for count in (2, 3, 4, 5, 6, 1, 1)
    ]
    target = cleanup.CleanupTarget(
        session_id=4,
        conversation_id=12,
        draft_agent_id=202,
        status="active",
        workflow_schema_version=2,
        reasons=("legacy_schema",),
    )

    counts = cleanup.soft_delete_cleanup_targets(
        db_session,
        [target],
        actor="nl2agent_cutover",
    )

    assert counts == {
        "installation_operations": 2,
        "conversation_sources_search": 3,
        "conversation_sources_image": 4,
        "conversation_message_units": 5,
        "conversation_messages": 6,
        "conversations": 1,
        "sessions": 1,
    }
    assert db_session.execute.call_count == 7


def test_count_cleanup_rows_reports_all_soft_delete_targets():
    db_session = MagicMock()
    results = []
    for count in (2, 3, 4, 5, 6, 1, 1):
        result = MagicMock()
        result.scalar_one.return_value = count
        results.append(result)
    db_session.execute.side_effect = results
    target = cleanup.CleanupTarget(
        session_id=4,
        conversation_id=12,
        draft_agent_id=202,
        status="active",
        workflow_schema_version=2,
        reasons=("legacy_schema",),
    )

    counts = cleanup.count_cleanup_rows(db_session, [target])

    assert counts == {
        "installation_operations": 2,
        "conversation_sources_search": 3,
        "conversation_sources_image": 4,
        "conversation_message_units": 5,
        "conversation_messages": 6,
        "conversations": 1,
        "sessions": 1,
    }


def test_run_cleanup_defaults_to_read_only_preview(monkeypatch, capsys):
    db_session = MagicMock()
    monkeypatch.setattr(
        cleanup.db_client, "session_maker", MagicMock(return_value=db_session)
    )
    monkeypatch.setattr(
        cleanup,
        "load_session_rows",
        MagicMock(return_value=[_legacy_session()]),
    )
    monkeypatch.setattr(
        cleanup,
        "load_conversation_rows",
        MagicMock(return_value=[_builder_conversation()]),
    )
    monkeypatch.setattr(
        cleanup,
        "count_cleanup_rows",
        MagicMock(return_value={"sessions": 1, "conversations": 1}),
    )

    result = cleanup.main(["--session-ids", "4", "--conversation-ids", "12"])

    assert result == 0
    statement = db_session.execute.call_args_list[0].args[0]
    assert str(statement) == "SET TRANSACTION READ ONLY"
    db_session.rollback.assert_called_once_with()
    db_session.commit.assert_not_called()
    db_session.close.assert_called_once_with()
    assert "no rows were changed" in capsys.readouterr().out


def test_run_cleanup_requires_exact_apply_confirmation(monkeypatch, capsys):
    session_maker = MagicMock()
    monkeypatch.setattr(cleanup.db_client, "session_maker", session_maker)

    result = cleanup.main(
        [
            "--session-ids",
            "4",
            "--conversation-ids",
            "12",
            "--apply",
            "--confirm",
            "wrong",
        ]
    )

    assert result == 1
    session_maker.assert_not_called()
    assert "--confirm must equal" in capsys.readouterr().err


def test_run_cleanup_rejects_oversized_batch_before_database_connection(
    monkeypatch, capsys
):
    session_maker = MagicMock()
    monkeypatch.setattr(cleanup.db_client, "session_maker", session_maker)
    args = SimpleNamespace(
        session_ids=list(range(1, cleanup.MAX_TARGETS + 2)),
        conversation_ids=list(range(1001, 1001 + cleanup.MAX_TARGETS + 1)),
        apply=False,
        confirm=None,
        actor=cleanup.DEFAULT_ACTOR,
    )

    result = cleanup.run_cleanup(args)

    assert result == 1
    session_maker.assert_not_called()
    assert "maximum cleanup batch size" in capsys.readouterr().err


def test_run_cleanup_commits_one_guarded_transaction(monkeypatch, capsys):
    db_session = MagicMock()
    target = cleanup.CleanupTarget(
        session_id=4,
        conversation_id=12,
        draft_agent_id=202,
        status="active",
        workflow_schema_version=2,
        reasons=("legacy_schema",),
    )
    monkeypatch.setattr(
        cleanup.db_client, "session_maker", MagicMock(return_value=db_session)
    )
    monkeypatch.setattr(
        cleanup, "load_session_rows", MagicMock(return_value=[_legacy_session()])
    )
    monkeypatch.setattr(
        cleanup,
        "load_conversation_rows",
        MagicMock(return_value=[_builder_conversation()]),
    )
    monkeypatch.setattr(
        cleanup,
        "validate_cleanup_targets",
        MagicMock(return_value=[target]),
    )
    monkeypatch.setattr(
        cleanup,
        "count_cleanup_rows",
        MagicMock(return_value={"sessions": 1, "conversations": 1}),
    )
    monkeypatch.setattr(
        cleanup,
        "soft_delete_cleanup_targets",
        MagicMock(return_value={"sessions": 1, "conversations": 1}),
    )

    result = cleanup.main(
        [
            "--session-ids",
            "4",
            "--conversation-ids",
            "12",
            "--apply",
            "--confirm",
            cleanup.APPLY_CONFIRMATION,
        ]
    )

    assert result == 0
    statement = db_session.execute.call_args_list[0].args[0]
    assert str(statement) == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
    db_session.commit.assert_called_once_with()
    db_session.rollback.assert_not_called()
    db_session.close.assert_called_once_with()
    assert "cleanup committed" in capsys.readouterr().out


def test_run_cleanup_redacts_database_errors(monkeypatch, capsys):
    db_session = MagicMock()
    db_session.execute.side_effect = RuntimeError(
        "postgresql://user:password@host/database"
    )
    monkeypatch.setattr(
        cleanup.db_client, "session_maker", MagicMock(return_value=db_session)
    )

    result = cleanup.main(["--session-ids", "4", "--conversation-ids", "12"])

    assert result == 2
    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert "password" not in error
    db_session.rollback.assert_called_once_with()
    db_session.close.assert_called_once_with()


def test_run_cleanup_redacts_session_creation_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        cleanup.db_client,
        "session_maker",
        MagicMock(side_effect=RuntimeError("postgresql://user:password@host/database")),
    )

    result = cleanup.main(["--session-ids", "4", "--conversation-ids", "12"])

    assert result == 2
    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert "password" not in error
