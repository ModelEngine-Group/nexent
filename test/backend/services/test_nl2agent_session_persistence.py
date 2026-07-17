"""Persistence integration tests kept separate from workflow behavior tests."""

from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
import redis

from agents import nl2agent_session_catalog as catalog
from agents import nl2agent_session_store as session_store
from agents.nl2agent_workflow import Nl2AgentWorkflowState, state_to_dict
from services.nl2agent_session_service import (
    SessionInitializationDependencies,
    start_session,
)
from services.nl2agent_publication_service import _persist_agent_update
from consts.exceptions import Nl2AgentOperationError
from utils.nl2agent_catalog_snapshot import catalog_snapshot_id


def _catalogs():
    return {
        "tool_catalog": [{"tool_id": 1}],
        "skill_catalog": [],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    }


def _snapshot(*, state=None):
    workflow_state = state or state_to_dict(Nl2AgentWorkflowState(conversation_id=902))
    snapshot_id = catalog_snapshot_id(_catalogs())
    return {
        "tenant_id": "tenant_1",
        "user_id": "user_1",
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "active",
        "workflow_revision": workflow_state["revision"],
        "catalog_snapshot_id": snapshot_id,
        "workflow_state": deepcopy(workflow_state),
        "catalog_snapshot": _catalogs(),
    }


@pytest.fixture
def durable_cache(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        catalog,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    monkeypatch.setattr(
        session_store,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    return client


def test_cache_miss_recovers_workflow_and_catalogs_from_database(
    durable_cache, monkeypatch
):
    load = MagicMock(return_value=_snapshot())
    monkeypatch.setattr(session_store, "load_durable_session", load)

    assert catalog.get_nl2agent_session_state("tenant_1", 202)["conversation_id"] == 902
    assert catalog.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()
    assert durable_cache.exists(catalog._state_key("tenant_1", 202))
    assert durable_cache.exists(catalog._cache_key("tenant_1", 202))
    snapshot_id = catalog_snapshot_id(_catalogs())
    assert durable_cache.exists(catalog._catalog_snapshot_key("tenant_1", snapshot_id))
    load.assert_called_once_with("tenant_1", 202)


def test_reads_fall_back_to_database_when_redis_is_unavailable(monkeypatch):
    client = MagicMock()
    client.get.side_effect = redis.ConnectionError("redis unavailable")
    monkeypatch.setattr(
        catalog,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    monkeypatch.setattr(
        session_store,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    load = MagicMock(return_value=_snapshot())
    monkeypatch.setattr(session_store, "load_durable_session", load)

    assert catalog.get_nl2agent_session_state("tenant_1", 202)["revision"] == 0
    assert catalog.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()
    assert load.call_count == 2


def test_workflow_mutation_persists_database_revision_before_cache(
    durable_cache, monkeypatch
):
    catalog.initialize_nl2agent_session_state("tenant_1", 202, conversation_id=902)
    persist = MagicMock(return_value=True)
    monkeypatch.setattr(session_store, "persist_workflow_state", persist)

    catalog.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Build an agent",
            "audience_or_scenario": "Operators",
            "primary_input": "Requests",
            "expected_output": "Actions",
            "key_constraints": "Use trusted resources",
        },
    )

    call = persist.call_args
    assert call.kwargs["expected_revision"] == 0
    assert call.kwargs["workflow_state"]["revision"] == 1
    assert catalog.get_nl2agent_session_state("tenant_1", 202)["revision"] == 1


def test_committed_workflow_mutation_survives_redis_write_failure(monkeypatch):
    real_client = fakeredis.FakeRedis(decode_responses=True)
    state = state_to_dict(Nl2AgentWorkflowState(conversation_id=902))
    real_client.set(catalog._state_key("tenant_1", 202), json.dumps(state))
    pipe = MagicMock(wraps=real_client.pipeline())
    pipe.execute.side_effect = redis.ConnectionError("redis write failed")
    client = MagicMock(wraps=real_client)
    client.pipeline.return_value = pipe
    monkeypatch.setattr(
        catalog,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    monkeypatch.setattr(
        session_store,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    monkeypatch.setattr(session_store, "persist_workflow_state", MagicMock(return_value=True))
    monkeypatch.setattr(session_store, "load_durable_session", MagicMock(return_value=_snapshot()))

    result = catalog.set_model_selection_confirmed("tenant_1", 202, True)

    assert result == {"model_selection_confirmed": True}


def test_database_conflict_recovers_and_retries_from_latest_revision(
    durable_cache, monkeypatch
):
    catalog.initialize_nl2agent_session_state("tenant_1", 202, conversation_id=902)
    latest = state_to_dict(Nl2AgentWorkflowState(conversation_id=902, revision=1))
    persist = MagicMock(side_effect=[False, True])
    monkeypatch.setattr(session_store, "persist_workflow_state", persist)
    monkeypatch.setattr(session_store, "load_durable_session", MagicMock(return_value=_snapshot(state=latest)))

    catalog.set_model_selection_confirmed("tenant_1", 202, True)

    assert [call.kwargs["expected_revision"] for call in persist.call_args_list] == [0, 1]
    assert catalog.get_nl2agent_session_state("tenant_1", 202)["revision"] == 2


def test_terminal_session_rejects_mutation_without_exhausting_retries(
    durable_cache, monkeypatch
):
    catalog.initialize_nl2agent_session_state("tenant_1", 202, conversation_id=902)
    persist = MagicMock(return_value=False)
    terminal = _snapshot()
    terminal["status"] = "completed"
    monkeypatch.setattr(session_store, "persist_workflow_state", persist)
    monkeypatch.setattr(session_store, "load_durable_session", MagicMock(return_value=terminal))

    with pytest.raises(catalog.Nl2AgentSessionCatalogError, match="no longer active"):
        catalog.set_model_selection_confirmed("tenant_1", 202, True)

    persist.assert_called_once()


def test_catalog_cache_uses_shared_content_addressed_snapshot(durable_cache):
    catalog.set_nl2agent_session_catalogs("tenant_1", 202, _catalogs())
    catalog.set_nl2agent_session_catalogs("tenant_1", 203, _catalogs())

    snapshot_id = catalog_snapshot_id(_catalogs())
    assert durable_cache.exists(catalog._catalog_snapshot_key("tenant_1", snapshot_id))
    assert durable_cache.get(catalog._cache_key("tenant_1", 202)) == json.dumps(
        {"snapshot_id": snapshot_id}
    )
    assert durable_cache.get(catalog._cache_key("tenant_1", 203)) == json.dumps(
        {"snapshot_id": snapshot_id}
    )


@contextmanager
def _database_transaction(session):
    yield session


@pytest.mark.asyncio
async def test_start_session_creates_snapshot_in_draft_transaction():
    db_session = MagicMock()
    create_snapshot = MagicMock()
    cache_state = MagicMock(return_value={"schema_version": 2, "revision": 0})
    cache_catalogs = MagicMock()
    dependencies = SessionInitializationDependencies(
        search_agent_id_by_name=MagicMock(return_value=101),
        search_agent_info_by_id=MagicMock(return_value={"agent_id": 101}),
        ensure_builder_ready=MagicMock(),
        load_session_catalogs=AsyncMock(return_value=(_catalogs(), [])),
        get_db_session=MagicMock(return_value=_database_transaction(db_session)),
        create_agent=MagicMock(return_value={"agent_id": 202}),
        create_conversation=MagicMock(return_value={"conversation_id": 902}),
        create_session_snapshot=create_snapshot,
        initialize_session_state=cache_state,
        set_session_catalogs=cache_catalogs,
        delete_session_catalogs=MagicMock(),
        new_uuid=MagicMock(return_value=MagicMock(hex="abcdef123456")),
        builder_agent_name="nl2agent",
        draft_name_prefix="draft_",
    )

    result = await start_session(
        dependencies,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
    )

    assert result["draft_agent_id"] == 202
    create_snapshot.assert_called_once_with(
        tenant_id="tenant_1",
        user_id="user_1",
        draft_agent_id=202,
        conversation_id=902,
        workflow_schema_version=2,
        workflow_state={"schema_version": 2, "revision": 0},
        session_catalogs=_catalogs(),
        db_session=db_session,
    )


def test_finalize_updates_agent_and_session_lifecycle_in_one_transaction():
    db_session = MagicMock()
    update_agent = MagicMock()
    complete_session = MagicMock(return_value=True)
    dependencies = SimpleNamespace(
        get_db_session=MagicMock(return_value=_database_transaction(db_session)),
        update_agent=update_agent,
        complete_session=complete_session,
    )

    _persist_agent_update(
        dependencies,
        agent_id=202,
        tenant_id="tenant_1",
        user_id="user_1",
        agent_update={"name": "document_helper", "display_name": "Document Helper"},
    )

    assert update_agent.call_args.kwargs["db_session"] is db_session
    complete_session.assert_called_once_with(
        tenant_id="tenant_1",
        draft_agent_id=202,
        status="completed",
        user_id="user_1",
        db_session=db_session,
    )


def test_finalize_rolls_back_when_session_is_no_longer_active():
    dependencies = SimpleNamespace(
        get_db_session=MagicMock(return_value=_database_transaction(MagicMock())),
        update_agent=MagicMock(),
        complete_session=MagicMock(return_value=False),
    )

    with pytest.raises(Nl2AgentOperationError, match="Failed to finalize"):
        _persist_agent_update(
            dependencies,
            agent_id=202,
            tenant_id="tenant_1",
            user_id="user_1",
            agent_update={"name": "document_helper", "display_name": "Document Helper"},
        )
