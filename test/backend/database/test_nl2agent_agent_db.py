from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from database import agent_db


@contextmanager
def _session_context(session):
    yield session


def test_query_agent_records_for_nl2agent_is_tenant_scoped(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    ordered_query = query.filter.return_value.order_by.return_value
    ordered_query.all.return_value = [SimpleNamespace(agent_id=12)]
    monkeypatch.setattr(agent_db, "get_db_session", lambda: _session_context(session))
    monkeypatch.setattr(agent_db, "as_dict", lambda record: {"agent_id": record.agent_id})

    assert agent_db.query_agent_records_for_nl2agent(12, "tenant-a") == [
        {"agent_id": 12}
    ]

    criteria = query.filter.call_args.args
    assert any("agent_id" in str(item) for item in criteria)
    assert any("tenant_id" in str(item) for item in criteria)


def test_update_agent_draft_fields_has_strict_identity_and_explicit_values(
    monkeypatch,
):
    session = MagicMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)
    monkeypatch.setattr(agent_db, "get_db_session", lambda: _session_context(session))
    monkeypatch.setattr(agent_db, "filter_property", lambda fields, _model: fields)

    rowcount = agent_db.update_agent_draft_fields(
        agent_id=12,
        tenant_id="tenant-a",
        fields={"description": "Updated", "example_questions": []},
    )

    assert rowcount == 1
    statement = session.execute.call_args.args[0]
    statement_text = str(statement)
    assert "agent_id" in statement_text
    assert "tenant_id" in statement_text
    assert "version_no" in statement_text
    assert "delete_flag" in statement_text
    assert {column.name for column in statement._values} == {
        "description",
        "example_questions",
    }


def test_update_agent_draft_fields_rejects_empty_values_without_querying(monkeypatch):
    get_session = MagicMock()
    monkeypatch.setattr(agent_db, "get_db_session", get_session)

    assert agent_db.update_agent_draft_fields(12, "tenant-a", {}) == 0
    get_session.assert_not_called()
