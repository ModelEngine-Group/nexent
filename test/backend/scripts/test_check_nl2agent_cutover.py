"""Tests for the read-only NL2AGENT cutover guard."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.scripts import check_nl2agent_cutover as cutover


def test_session_evaluation_rejects_v2_and_legacy_keys():
    issues = cutover.evaluate_session_rows(
        [
            {
                "session_id": 7,
                "status": "active",
                "workflow_schema_version": 2,
                "workflow_state": {
                    "schema_version": 2,
                    "card_delivery": {},
                    "nested": {"online_installations": {}},
                },
            }
        ]
    )

    assert [issue.code for issue in issues] == [
        "active_schema_mismatch",
        "legacy_workflow_state",
    ]
    assert "card_delivery" in issues[1].detail
    assert "online_installations" in issues[1].detail


def test_v3_sessions_and_bound_builder_conversations_pass():
    assert (
        cutover.evaluate_session_rows(
            [
                {
                    "session_id": 8,
                    "status": "active",
                    "workflow_schema_version": 3,
                    "workflow_state": {"schema_version": 3},
                }
            ]
        )
        == []
    )
    assert (
        cutover.evaluate_builder_conversation_rows(
            [{"conversation_id": 9, "v3_session_id": 8}]
        )
        == []
    )


def test_orphan_builder_conversation_blocks_cutover():
    issues = cutover.evaluate_builder_conversation_rows(
        [{"conversation_id": 91, "v3_session_id": None}]
    )

    assert len(issues) == 1
    assert issues[0].code == "legacy_builder_conversation"
    assert issues[0].identifier == 91


def test_main_returns_nonzero_when_issues_exist(monkeypatch, capsys):
    @contextmanager
    def transaction():
        yield object()

    monkeypatch.setattr(cutover, "_read_only_db_session", transaction)
    monkeypatch.setattr(
        cutover,
        "inspect_nl2agent_cutover",
        lambda _session: [
            cutover.CutoverIssue(
                code="active_schema_mismatch",
                subject="session",
                identifier=7,
                detail="active Session is not workflow schema v3",
            )
        ],
    )

    assert cutover.main() == 1
    assert "cutover blocked" in capsys.readouterr().err


def test_main_fails_closed_without_printing_connection_details(monkeypatch, capsys):
    @contextmanager
    def failed_transaction():
        raise RuntimeError("postgresql://user:password@host/database")
        yield

    monkeypatch.setattr(cutover, "_read_only_db_session", failed_transaction)

    assert cutover.main() == 2
    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert "password" not in error


def test_read_only_session_enforces_transaction_and_always_closes(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        cutover.db_client, "session_maker", MagicMock(return_value=session)
    )

    with cutover._read_only_db_session() as yielded:
        assert yielded is session

    statement = session.execute.call_args.args[0]
    assert str(statement) == "SET TRANSACTION READ ONLY"
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
