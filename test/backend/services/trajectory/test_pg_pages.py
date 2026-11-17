# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Database-backed page snapshots and facets enforce bounds and trusted scopes."""

from unittest.mock import Mock

import pytest
from ops.services.trajectory.access import Actor
from ops.services.trajectory.cache import ByteCache
from ops.services.trajectory.pg_collection import facets, records
from ops.services.trajectory.primitives import QueryError, ReferenceStore

ACTOR = Actor("admin", "t", "OPS")


@pytest.fixture
def service():
    instance = Mock(max_candidates=100)
    instance.references = ReferenceStore()
    instance.queries = ByteCache()
    instance.catalog.actor_active.return_value = True
    instance.catalog.tenants.return_value = ["t", "v"]
    instance.catalog.names.return_value = {"t": "Tenant", "v": "Second"}
    instance.catalog.agent_names.return_value = {("t", "7"): "7", ("t", "8"): "Agent"}
    instance.catalog.builtin_agent_ids.return_value = set()
    instance.execution_catalog.statistics.return_value = {"complete": True}
    instance.execution_catalog.list_records.return_value = [
        {
            "tenant_id": "t",
            "user_id": "u",
            "conversation_id": str(i),
            "root_agent_id": agent,
            "usage": {"total": tokens},
            "_runs": [],
        }
        for i, agent, tokens in ((1, "7", None), (2, "8", 20), (3, None, 10))
    ]
    return instance


def test_token_sort_places_unknown_last_and_preserves_frozen_members(service):
    result = records(
        service, ACTOR, {}, sort_by="total_tokens", sort_order="asc", all_items=True
    )
    assert [i["conversation_id"] for i in result["items"]] == ["3", "2", "1"]
    assert result["items"][2]["root_agent_name"] is None
    assert result["items"][1]["root_agent_name"] == "Agent"
    assert all("_runs" not in i for i in result["items"])
    service.queries.entries.clear()
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(service, ACTOR, {}, query_id=result["query_id"])


def test_pg_membership_survives_switching_cache_clients(service):
    import fakeredis
    from ops.services.trajectory.redis_cache import RedisByteCache

    server = fakeredis.FakeServer()
    clients = [fakeredis.FakeRedis(server=server) for _ in range(2)]
    try:
        service.references = ReferenceStore(cache=RedisByteCache(clients[0], namespace="references"))
        service.queries = RedisByteCache(clients[0], namespace="queries")
        first = records(service, ACTOR, {}, page_size=1)
        service.references = ReferenceStore(cache=RedisByteCache(clients[1], namespace="references"))
        service.queries = RedisByteCache(clients[1], namespace="queries")
        service.execution_catalog.list_records.side_effect = AssertionError("Frozen list was recomputed")
        second = records(service, ACTOR, {}, page_size=1, page=2, query_id=first["query_id"])
        assert first["total"] == second["total"] == 3
        assert first["as_of"] == second["as_of"]
        assert first["items"][0]["conversation_id"] != second["items"][0]["conversation_id"]
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize(
    "params",
    [
        {"view": "bad"},
        {"page": 0},
        {"page_size": 101},
        {"sort_by": "private"},
        {"sort_order": "bad"},
    ],
)
def test_invalid_page_parameters_never_query_database(service, params):
    with pytest.raises(QueryError, match="invalid_parameters"):
        records(service, ACTOR, {}, **params)
    service.execution_catalog.list_records.assert_not_called()


def test_membership_cache_and_response_size_are_bounded(service):
    service.queries = ByteCache(max_bytes=1)
    with pytest.raises(QueryError, match="query_membership_budget_exceeded"):
        records(service, ACTOR, {})
    service.queries = ByteCache(max_bytes=32 * 1024 * 1024)
    service.execution_catalog.list_records.return_value[0]["conversation_title"] = (
        "x" * (2 * 1024 * 1024)
    )
    with pytest.raises(QueryError, match="record_page_budget_exceeded"):
        records(service, ACTOR, {}, all_items=True)


def test_global_statistics_scope_is_rechecked_before_return(service):
    actor = Actor("admin", "", "SU")
    service.catalog.tenants.side_effect = [["t"], ["t", "v"]]
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(service, actor, {})
    service.execution_catalog.statistics.assert_called_once_with(
        ["t"], global_scope=True
    )


@pytest.mark.parametrize("facet,limit", [("bad", 20), ("users", 0), ("users", 101)])
def test_invalid_facet_rejected_before_lookup(service, facet, limit):
    with pytest.raises(QueryError, match="invalid_facet"):
        facets(service, ACTOR, {}, facet, limit=limit)
    service.catalog.user_page.assert_not_called()


def test_tenant_facet_search_and_cursor_are_bound_to_scope(service):
    actor = Actor("admin", "", "SU")
    first = facets(service, actor, {}, "tenants", limit=1)
    assert first["items"] == [{"id": "t", "name": "Tenant", "tenant_id": "t"}]
    second = facets(service, actor, {}, "tenants", limit=1, cursor=first["next_cursor"])
    assert second["items"][0]["id"] == "v" and second["next_cursor"] is None
    assert (
        facets(service, actor, {}, "tenants", search="SECOND")["items"][0]["id"] == "v"
    )
    with pytest.raises(QueryError, match="invalid_reference"):
        facets(
            service, actor, {}, "tenants", search="changed", cursor=first["next_cursor"]
        )


@pytest.mark.parametrize("facet", ["users", "agents", "models", "conversations"])
def test_facets_enrich_only_the_appropriate_labels_and_continue_by_key(service, facet):
    options = [
        {"id": "7", "tenant_id": "t", "name": "name"},
        {"id": "8", "tenant_id": "t", "name": "other"},
    ]
    service.catalog.user_page.return_value = options
    service.execution_catalog.facets.return_value = options
    first = facets(service, ACTOR, {"agent_id": "7"}, facet, search=" Q ", limit=1)
    state = service.references.resolve(first["next_cursor"], "facet")
    assert state["after"] == ["t", "7"] and state["search"] == "q"
    if facet == "users":
        assert first["items"][0]["tenant_name"] == "Tenant"
        service.catalog.user_page.assert_called_once_with(["t", "v"], "q", None, 1)
    elif facet == "agents":
        assert first["items"][0]["name"] == "7"
    else:
        service.execution_catalog.facets.assert_called_once_with(
            ["t", "v"], {"agent_id": "7"}, facet, "q", None, 1
        )
