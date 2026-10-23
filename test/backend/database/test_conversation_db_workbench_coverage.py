from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test.backend.database import test_conversation_db as legacy


conversation_db = __import__(
    "backend.database.conversation_db", fromlist=["create_conversation"]
)


def _session(monkeypatch):
    session = MagicMock()

    @contextmanager
    def get_session():
        yield session

    monkeypatch.setattr(conversation_db, "get_db_session", get_session)
    return session


def test_create_conversation_persists_initial_workbench_version(monkeypatch):
    session = _session(monkeypatch)
    record = SimpleNamespace(
        conversation_id=42,
        conversation_title="Workbench",
        agent_id=7,
        chat_mode="execution",
        knowledge_scope=None,
        runtime_metadata={},
        runtime_metadata_version=0,
        workbench_config={"schema_version": 3, "mode": "single_agent_chat"},
        workbench_config_version=1,
        create_time=1000,
        update_time=1000,
    )
    session.execute.return_value.fetchone.return_value = record

    result = conversation_db.create_conversation(
        "Workbench",
        "user-a",
        agent_id=7,
        workbench_config={"schema_version": 3, "mode": "single_agent_chat"},
    )

    assert result["workbench_config_version"] == 1
    assert result["workbench_config"]["mode"] == "single_agent_chat"
    assert legacy._captured_insert_values["workbench_config_version"] == 1


@pytest.mark.parametrize(
    "function_name",
    ["replace_conversation_workbench_config", "replace_conversation_workbench_and_metadata"],
)
def test_workbench_replacement_requires_owned_conversation(
    monkeypatch, function_name
):
    session = _session(monkeypatch)
    session.scalars.return_value.first.return_value = None
    function = getattr(conversation_db, function_name)
    common = {
        "conversation_id": 42,
        "user_id": "user-a",
        "config": {"schema_version": 3, "mode": "generic_chat"},
    }

    with pytest.raises(conversation_db.ConversationNotFoundError):
        if function_name.endswith("and_metadata"):
            function(
                **common,
                expected_config_version=0,
                metadata={},
                expected_metadata_version=0,
            )
        else:
            function(**common, expected_version=0)


def test_creation_topology_accepts_same_creation_mode():
    record = SimpleNamespace(
        workbench_config={"schema_version": 3, "mode": "skill_create"}
    )

    conversation_db._assert_workbench_topology(
        record, {"schema_version": 3, "mode": "skill_create"}
    )


def test_conversation_list_rejects_unknown_origin():
    with pytest.raises(ValueError, match="Invalid conversation type"):
        conversation_db.get_conversation_list_page(
            "user-a", 1000, 500, conversation_type="unknown"
        )


@pytest.mark.parametrize("rowcount, expected", [(1, True), (0, False)])
def test_rebind_conversation_agent_id_reports_compare_and_swap_result(
    monkeypatch, rowcount, expected
):
    session = _session(monkeypatch)
    session.execute.return_value.rowcount = rowcount

    assert (
        conversation_db.rebind_conversation_agent_id(42, 7, 8, "user-a")
        is expected
    )
