import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from agents import nl2agent_session_store as session_store
from agents.nl2agent_workflow import (
    Nl2AgentWorkflowState,
    RecommendationBatch,
    state_to_dict,
)
from utils.nl2agent_catalog_snapshot import create_catalog_snapshot


_CATALOG_VERSION = "catalog_11111111111111111111111111111111"


def _catalogs():
    return {
        "tool_catalog": [{"tool_id": 1}],
        "skill_catalog": [{"skill_id": 2}],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    }


def _snapshot(*, revision=0, status="active"):
    state = Nl2AgentWorkflowState(conversation_id=902, revision=revision)
    return {
        "tenant_id": "tenant_1",
        "user_id": "user_1",
        "runner_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": status,
        "workflow_revision": revision,
        "workflow_state": state_to_dict(state),
        "session_catalogs": create_catalog_snapshot(
            _catalogs(), catalog_version=_CATALOG_VERSION
        ),
    }


def test_workflow_state_serializes_only_unified_recommendations():
    state = Nl2AgentWorkflowState(
        conversation_id=902,
        recommendations={
            "local": RecommendationBatch(resource_type="local", status="searched")
        },
    )

    payload = state_to_dict(state)

    assert payload["recommendations"]["local"]["resource_type"] == "local"
    assert "trusted_search_batches" not in payload
    assert "recommendation_batches" not in payload
    assert "online_recommendation_batches" not in payload


@pytest.mark.parametrize(
    "legacy_field",
    [
        "trusted_search_batches",
        "recommendation_batches",
        "online_recommendation_batches",
    ],
)
def test_legacy_recommendation_fields_are_rejected(legacy_field):
    payload = state_to_dict(Nl2AgentWorkflowState(conversation_id=902))
    payload[legacy_field] = {}

    with pytest.raises(session_store.Nl2AgentSessionCatalogError, match="Malformed"):
        session_store.parse_session_state(json.dumps(payload), "tenant_1", 202)


def test_state_and_catalogs_are_read_only_from_postgresql(monkeypatch):
    snapshot = _snapshot()
    load = MagicMock(return_value=deepcopy(snapshot))
    monkeypatch.setattr(session_store, "load_durable_session", load)

    assert session_store.get_session_state("tenant_1", 202)["revision"] == 0
    catalogs = session_store.get_session_catalogs("tenant_1", 202)
    catalogs["tool_catalog"].append({"tool_id": 999})

    assert session_store.get_session_catalogs("tenant_1", 202) == _catalogs()
    assert load.call_count == 3


def test_postgresql_failure_does_not_fall_back_to_a_cache(monkeypatch):
    monkeypatch.setattr(
        session_store,
        "load_durable_session",
        MagicMock(side_effect=RuntimeError("postgres unavailable")),
    )

    with pytest.raises(session_store.Nl2AgentSessionCatalogError, match="Failed to load"):
        session_store.get_session_state("tenant_1", 202)

    assert not hasattr(session_store, "refresh_cache_best_effort")
    assert not hasattr(session_store, "recover_committed_cache_best_effort")


def test_workflow_mutation_advances_database_revision_once(monkeypatch):
    durable = _snapshot()

    def load(*_):
        return deepcopy(durable)

    def persist(_tenant, _draft, expected_revision, workflow_state):
        assert expected_revision == durable["workflow_revision"]
        durable["workflow_revision"] = workflow_state["revision"]
        durable["workflow_state"] = deepcopy(workflow_state)
        return True

    monkeypatch.setattr(session_store, "load_durable_session", load)
    monkeypatch.setattr(session_store, "persist_workflow_state", persist)

    result = session_store.mutate_session_state(
        "tenant_1", 202, lambda state: setattr(state.requirements_review, "status", "confirmed")
    )

    assert result is None
    assert durable["workflow_revision"] == 1
    assert durable["workflow_state"]["requirements_review"]["status"] == "confirmed"


def test_database_cas_conflict_reloads_and_retries(monkeypatch):
    durable = _snapshot()
    persist_calls = 0

    def load(*_):
        return deepcopy(durable)

    def persist(_tenant, _draft, expected_revision, workflow_state):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            durable["workflow_revision"] = 1
            durable["workflow_state"]["revision"] = 1
            return False
        assert expected_revision == 1
        durable["workflow_revision"] = workflow_state["revision"]
        durable["workflow_state"] = deepcopy(workflow_state)
        return True

    monkeypatch.setattr(session_store, "load_durable_session", load)
    monkeypatch.setattr(session_store, "persist_workflow_state", persist)

    session_store.mutate_session_state(
        "tenant_1", 202, lambda state: setattr(state.requirements_review, "status", "confirmed")
    )

    assert persist_calls == 2
    assert durable["workflow_revision"] == 2


def test_terminal_session_rejects_mutation(monkeypatch):
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=_snapshot(status="completed"))
    )

    with pytest.raises(session_store.Nl2AgentSessionCatalogError, match="no longer active"):
        session_store.mutate_session_state("tenant_1", 202, lambda state: None)


def test_catalog_validation_returns_a_deep_copy():
    source = create_catalog_snapshot(_catalogs(), catalog_version=_CATALOG_VERSION)
    validated = session_store.validate_catalogs(source)
    source["tool_catalog"][0]["tool_id"] = 99
    assert validated["tool_catalog"] == [{"tool_id": 1}]


@pytest.mark.parametrize("tenant_id,draft_agent_id", [(None, 1), ("tenant", None), ("", 2)])
def test_session_identity_requires_tenant_and_draft(tenant_id, draft_agent_id):
    with pytest.raises(session_store.Nl2AgentSessionCatalogError):
        session_store.validate_identifiers(tenant_id, draft_agent_id)
