# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Standalone file queries retain their bounds, snapshots and facet isolation."""

from unittest.mock import Mock

import pytest
import test_collection as fixtures
from ops.services.trajectory.access import Actor
from ops.services.trajectory.cache import ByteCache
from ops.services.trajectory.collection import _matches, facets, records
from ops.services.trajectory.primitives import QueryError

service = fixtures.service
ACTOR = Actor("admin", "t", "OPS")


@pytest.mark.parametrize(
    "params",
    [
        {"view": "invalid"},
        {"filters": {"status": "expired"}},
        {"page": 0},
        {"page_size": 0},
        {"sort_by": "secret"},
        {"sort_order": "invalid"},
    ],
)
def test_invalid_query_never_scans_files(service, params):
    with pytest.raises(QueryError, match="invalid_parameters"):
        records(service, ACTOR, **{"filters": {}, **params})
    service.archive.manifest.assert_not_called()


@pytest.mark.parametrize(
    "facet", ["tenants", "users", "agents", "conversations", "models"]
)
def test_standalone_facets_use_authorized_names_and_model_scope(service, facet):
    service.catalog.agent_names.return_value = {("t", "7"): "Agent"}
    service.catalog.user_page.return_value = [
        {"id": "u", "name": "Owner", "tenant_id": "t"}
    ]
    service.catalog.user_active.return_value = True
    response = facets(service, ACTOR, {}, facet, search="")
    assert len(response["items"]) == 1 and response["next_cursor"] is None
    assert (
        response["items"][0]["id"]
        == {
            "tenants": "t",
            "users": "u",
            "agents": "7",
            "conversations": "1",
            "models": "model",
        }[facet]
    )
    if facet == "users":
        assert response["items"][0]["tenant_name"] == "Tenant"
        service.catalog.user_active.return_value = False
        assert facets(service, ACTOR, {}, facet)["items"] == []


def test_facet_cursor_keeps_search_and_filter_binding(service):
    service.catalog.user_page.return_value = [
        {"id": name, "name": name, "tenant_id": "t"} for name in ("a", "b")
    ]
    service.catalog.user_active.return_value = True
    first = facets(service, ACTOR, {}, "users", limit=1)
    second = facets(service, ACTOR, {}, "users", limit=1, cursor=first["next_cursor"])
    assert first["items"][0]["id"] == "a" and second["items"][0]["id"] == "b"
    assert not second["next_cursor"]
    for facet, limit in (("bad", 20), ("users", 0)):
        with pytest.raises(QueryError, match="invalid_facet"):
            facets(service, ACTOR, {}, facet, limit=limit)


@pytest.mark.parametrize("status", [404, 503])
def test_missing_or_failed_owner_lookup_does_not_return_partial_aggregates(
    service, status
):
    service.catalog.resolve.side_effect = QueryError("lookup_failed", status)
    if status == 404:
        assert records(service, ACTOR, {})["total"] == 0
    else:
        with pytest.raises(QueryError, match="lookup_failed"):
            records(service, ACTOR, {})


@pytest.mark.parametrize("status", [404, 503])
def test_manifest_lookup_failure_in_records_and_facets(service, status):
    service.archive.manifest.side_effect = QueryError("archive_failed", status)
    for read in (
        lambda: records(service, ACTOR, {}),
        lambda: facets(service, ACTOR, {}, "agents"),
    ):
        if status == 404:
            assert read()["items"] == []
        else:
            with pytest.raises(QueryError, match="archive_failed"):
                read()


def test_membership_and_response_byte_limits_are_explicit(service):
    service.queries = ByteCache(max_bytes=1)
    with pytest.raises(QueryError, match="query_membership_budget_exceeded"):
        records(service, ACTOR, {})
    service.queries = ByteCache(max_bytes=64 * 1024 * 1024)
    service.catalog.resolve.return_value["conversation_title"] = "x" * (2 * 1024 * 1024)
    with pytest.raises(QueryError, match="record_page_budget_exceeded"):
        records(service, ACTOR, {})


@pytest.mark.parametrize(
    "filters",
    [
        {"agent_id": "other"},
        {"status": "error"},
        {"started_from": "2026-01-01T00:00:00Z"},
        {"started_to": "2026-01-01T00:00:00Z"},
    ],
)
def test_final_predicates_reject_mismatch_and_unknown_start_time(filters):
    item = {"root_agent_id": "7", "status": "success", "started_at": None}
    assert not _matches(item, [], filters)


def test_pg_configured_service_dispatches_without_filesystem_query(service, mocker):
    service.execution_catalog = Mock()
    pg_records = mocker.patch(
        "ops.services.trajectory.pg_collection.records", return_value={"items": []}
    )
    pg_facets = mocker.patch(
        "ops.services.trajectory.pg_collection.facets", return_value={"items": []}
    )
    assert records(service, ACTOR, {}) == {"items": []}
    assert facets(service, ACTOR, {}, "agents") == {"items": []}
    pg_records.assert_called_once()
    pg_facets.assert_called_once()
    service.archive.manifest.assert_not_called()
