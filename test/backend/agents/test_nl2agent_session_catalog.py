import json
from unittest.mock import MagicMock

import pytest

from agents import nl2agent_session_catalog as catalog_module


class FakeRedis:
    def __init__(self):
        self.data = {}

    def setex(self, key, ttl, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def scan_iter(self, match):
        prefix = match.removesuffix("*")
        return (key for key in self.data if key.startswith(prefix))

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(
        catalog_module,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    return client


def _catalogs():
    return {
        "tool_catalog": [{"tool_id": 1}],
        "skill_catalog": [{"skill_id": 2}],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    }


def test_catalogs_round_trip_through_shared_redis(fake_redis, monkeypatch):
    catalog_module.set_nl2agent_session_catalogs("tenant_1", 202, _catalogs())

    # A newly created service facade simulates a separate runtime worker while
    # retaining the same shared Redis storage.
    monkeypatch.setattr(
        catalog_module,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=fake_redis)),
    )

    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()


def test_missing_catalogs_raise_contextual_error(fake_redis, caplog):
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

    assert "NL2AGENT catalogs are missing" in caplog.text


def test_malformed_catalogs_raise_contextual_error(fake_redis, caplog):
    key = catalog_module._cache_key("tenant_1", 202)
    fake_redis.data[key] = json.dumps({"tool_catalog": "not-a-list"})

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

    assert "Malformed NL2AGENT catalogs" in caplog.text


def test_recommendation_batch_registration_is_idempotent_and_requires_resolution(fake_redis):
    first = catalog_module.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [3, 1], [7]
    )
    second = catalog_module.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [1, 3], [7]
    )
    assert first == second
    assert first["status"] == "recommendations_ready"

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError, match="Apply or skip"
    ):
        catalog_module.assert_resource_review_complete("tenant_1", 202)

    catalog_module.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "applied", [1], [7]
    )
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_empty_recommendation_batch_can_be_explicitly_skipped(fake_redis):
    catalog_module.register_recommendation_batch(
        "tenant_1", 202, "empty_batch", [], []
    )
    catalog_module.resolve_recommendation_batch(
        "tenant_1", 202, "empty_batch", "skipped"
    )
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_identity_confirmation_round_trip(fake_redis):
    assert not catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "identity_confirmed"
    ]
    catalog_module.confirm_agent_identity("tenant_1", 202)
    assert catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "identity_confirmed"
    ]


def test_mcp_workflow_blocks_connected_and_resolves_after_binding_or_skip(fake_redis):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        option_id="remote-0",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11, 12],
        bound_tool_ids=[],
    )
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Bind discovered"):
        catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)

    catalog_module.update_mcp_workflow(
        "tenant_1", 202, "registry:github", status="tools_bound", bound_tool_ids=[11]
    )
    catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)
    workflow = catalog_module.get_nl2agent_session_state("tenant_1", 202)["mcp_workflows"][
        "registry:github"
    ]
    assert "config_values" not in workflow


def test_session_state_is_isolated_by_tenant_and_draft(fake_redis):
    catalog_module.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [1], []
    )
    assert catalog_module.get_nl2agent_session_state("tenant_1", 303) == {
        "recommendation_batches": {},
        "identity_confirmed": False,
        "mcp_workflows": {},
    }
    assert catalog_module.get_nl2agent_session_state("tenant_2", 202) == {
        "recommendation_batches": {},
        "identity_confirmed": False,
        "mcp_workflows": {},
    }
