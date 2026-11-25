# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Elasticsearch completeness, idempotency, paging and template contracts."""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from elasticsearch import NotFoundError

from ops.monitoring import search
from ops.monitoring.model import MODEL_MONITORING
from ops.monitoring import query


def missing():
    return NotFoundError("missing", meta=MagicMock(status=404), body={})


@pytest.mark.parametrize("existing", [False, True])
def test_templates_extend_both_existing_indices_and_future_partitions(existing):
    es = MagicMock()
    es.indices.get.side_effect = [{"facts-old": {}} if existing else {}, {"daily-old": {}} if existing else {}]
    search.install_templates(es, 0, [MODEL_MONITORING])
    assert es.indices.put_index_template.call_count == 2
    facts, daily = [c.kwargs for c in es.indices.put_index_template.call_args_list]
    assert facts["index_patterns"] == ["monitoring-facts-*"]
    assert daily["index_patterns"] == ["monitoring-daily-*"]
    for template in (facts, daily):
        assert template["template"]["settings"] == {"number_of_shards": 1, "number_of_replicas": 0}
        assert template["template"]["mappings"]["dynamic"] == "strict"
    assert facts["template"]["mappings"]["properties"]["input_tokens"] == {"type": "long"}
    assert daily["template"]["mappings"]["properties"]["request_count"] == {"type": "long"}
    assert es.indices.put_mapping.call_count == (2 if existing else 0)
    if existing:
        assert es.indices.put_mapping.call_args_list[0].kwargs["index"] == ["facts-old"]


def test_existing_fact_distinguishes_not_found_from_transport_failure():
    es = MagicMock()
    es.get.return_value = {"_source": {"record_revision": 2}}
    assert search.existing_fact(es, "facts", "f") == {"record_revision": 2}
    es.get.side_effect = missing()
    assert search.existing_fact(es, "facts", "f") is None
    es.get.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        search.existing_fact(es, "facts", "f")


@pytest.fixture
def write():
    return {"index": "facts", "id": "f", "document": {"write_version": 7, "outcome": "succeeded"}}


@pytest.mark.parametrize("external", [False, True])
def test_bulk_writes_use_external_versions_only_for_facts(write, external):
    es = MagicMock()
    es.bulk.return_value = {"items": [{"index": {"status": 201, "_shards": {"failed": 0}}}]}
    search.bulk_write(es, [write], external=external)
    action = {"_index": "facts", "_id": "f"}
    if external:
        action.update(version=7, version_type="external")
    es.bulk.assert_called_once_with(operations=[{"index": action}, write["document"]], refresh="wait_for")
    es.indices.refresh.assert_not_called()


def test_empty_bulk_does_not_call_es():
    es = MagicMock()
    search.bulk_write(es, [], external=True)
    search.delete_documents(es, iter([]))
    es.bulk.assert_not_called()


@pytest.mark.parametrize("items", [[], [{"index": {"status": 503}}],
                                   [{"index": {"status": 201, "_shards": {"failed": 1}}}]])
def test_bulk_rejects_missing_results_errors_and_partial_replicas(write, items):
    es = MagicMock()
    es.bulk.return_value = {"items": items}
    with pytest.raises(RuntimeError):
        search.bulk_write(es, [write], external=True)


@pytest.mark.parametrize("same,external,refresh_failed", [(True, True, False), (False, True, False),
                                                         (True, False, False), (True, True, True)])
def test_version_conflict_requires_exact_document_and_successful_refresh(write, same, external, refresh_failed):
    es = MagicMock()
    es.bulk.return_value = {"items": [{"index": {"status": 409}}]}
    es.get.return_value = {"_source": write["document"] if same else {"write_version": 8}}
    es.indices.refresh.return_value = {"_shards": {"failed": int(refresh_failed)}}
    if same and external and not refresh_failed:
        search.bulk_write(es, [write], external=external)
    else:
        with pytest.raises(RuntimeError):
            search.bulk_write(es, [write], external=external)
    if same and external:
        es.indices.refresh.assert_called_once_with(index=["facts"])
    else:
        es.indices.refresh.assert_not_called()


def test_delete_batches_snapshot_ids_and_accepts_already_deleted_documents():
    es, batches = MagicMock(), []

    def bulk(*, operations):
        batches.append(deepcopy(operations))
        return {"items": [{"delete": {"status": 200 if i % 2 else 404}} for i in range(len(operations))]}

    es.bulk.side_effect = bulk
    search.delete_documents(es, iter({"_index": "daily", "_id": str(i)} for i in range(501)))
    assert [len(batch) for batch in batches] == [500, 1]
    assert batches[0][0] == {"delete": {"_index": "daily", "_id": "0"}}
    assert batches[-1][-1] == {"delete": {"_index": "daily", "_id": "500"}}


@pytest.mark.parametrize("items", [[], [{"delete": {"status": 403}}],
                                   [{"delete": {"status": 200, "_shards": {"failed": 1}}}]])
def test_incomplete_deletion_is_an_error(items):
    es = MagicMock()
    es.bulk.return_value = {"items": items}
    with pytest.raises(RuntimeError):
        search.delete_documents(es, iter([{"_index": "daily", "_id": "f"}]))


def page(hits, **changes):
    return {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": hits}, **changes}


def test_snapshot_pagination_tracks_rotated_pit_and_search_after():
    es = MagicMock()
    es.open_point_in_time.return_value = {"id": "first"}
    es.search.side_effect = [page([{"_source": {"request_count": 1}, "sort": [7]}], pit_id="second"),
                             page([{"_source": {"request_count": 2}, "sort": [9]}], pit_id="third"), page([])]
    query = search.filters(tenant_id="t", statistic_date=["2026-11-23"])
    with search.snapshot(es, "daily-*") as point:
        assert list(point.documents(query)) == [{"request_count": 1}, {"request_count": 2}]
    calls = [c.kwargs for c in es.search.call_args_list]
    assert [c["search_after"] for c in calls] == [None, [7], [9]]
    assert [c["pit"]["id"] for c in calls] == ["first", "second", "third"]
    assert all(c["allow_partial_search_results"] is False and c["source"] is True for c in calls)
    es.close_point_in_time.assert_called_once_with(id="third")


@pytest.mark.parametrize("failure", ["timeout", "shards", "body"])
def test_snapshot_closes_latest_id_on_failed_read_or_caller_error(failure):
    es = MagicMock()
    es.open_point_in_time.return_value = {"id": "first"}
    es.search.return_value = page([], pit_id="latest", timed_out=failure == "timeout",
                                 _shards={"failed": int(failure == "shards")})
    with pytest.raises(RuntimeError):
        with search.snapshot(es, "daily-*") as point:
            list(point.hits({}, source=False))
            raise RuntimeError("caller failed")
    es.close_point_in_time.assert_called_once_with(id="latest")
    assert es.search.call_args.kwargs["source"] is False


def test_incomplete_snapshot_open_is_closed_and_never_yielded():
    es = MagicMock()
    es.open_point_in_time.return_value = {"id": "partial", "_shards": {"failed": 1}}
    with pytest.raises(RuntimeError, match="Incomplete"):
        with search.snapshot(es, "daily-*"):
            pytest.fail("Incomplete point in time must not be exposed")
    es.close_point_in_time.assert_called_once_with(id="partial")


def test_skill_catalog_filters_deleted_rows_and_normalizes_database_mappings(monkeypatch):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            self.statement = statement
            return SimpleNamespace(mappings=lambda: iter([
                {"tenant_id": "tenant", "skill_id": 7, "skill_name": "summarize"},
            ]))

    session = Session()
    monkeypatch.setattr(query, "get_db_session", lambda: session)
    assert query.skill_catalog("tenant") == [
        {"tenant_id": "tenant", "skill_id": 7, "skill_name": "summarize"}
    ]
    assert "tenant_id" in str(session.statement)


def test_read_skills_applies_filters_and_builds_publication_status(monkeypatch):
    service = SimpleNamespace(store=SimpleNamespace(has_failed_batches=lambda *args: True))
    published = [{"statistic_date": "2026-11-23"}]
    states = [{"tenant_id": "tenant", "source_revision": 2, "published_source_revision": 1}]
    monkeypatch.setattr(query, "_read_published_rows", lambda *args, **kwargs: (
        [{"tenant_id": "tenant", "skill_id": "7", "usage_count": 3}], states, published,
    ))
    monkeypatch.setattr(query, "skill_catalog", lambda tenant: [
        {"tenant_id": tenant, "skill_id": 7, "skill_name": "summarize"},
        {"tenant_id": tenant, "skill_id": 8, "skill_name": "other"},
    ])
    monkeypatch.setattr(query, "_publication_status", lambda *args, **kwargs: {
        "coverage_state": "partial", "is_stale": True, "data_as_of": None,
    })
    result = query.read_skills(service, tenant="tenant", start=date(2026, 11, 23), end=date(2026, 11, 23),
                               groups=[3], skill_id="7", skill_name="summarize")
    assert result == (
        [{"tenant_id": "tenant", "skill_id": "7", "usage_count": 3}],
        [{"tenant_id": "tenant", "skill_id": "7", "skill_name": "summarize"}],
        ["2026-11-23"], {"coverage_state": "partial", "is_stale": True, "data_as_of": None},
    )


def test_skill_rows_keeps_inventory_only_rows_uncovered_and_ignores_missing_ids():
    rows = [
        {"tenant_id": "tenant", "skill_id": 7, "skill_name": "summarize", "usage_count": 2},
        {"tenant_id": "tenant", "skill_id": None, "skill_name": "ignored", "usage_count": 99},
        {"tenant_id": "tenant", "skill_id": 8, "skill_name": "discovered", "usage_count": 1},
    ]
    inventory = [{"tenant_id": "tenant", "skill_id": "7", "skill_name": "summarize"},
                 {"tenant_id": "tenant", "skill_id": "9", "skill_name": "unused"}]
    result = query.skill_rows(rows, inventory, covered=False)
    assert {item["skill_id"] for item in result} == {"7", "8", "9"}
    assert next(item for item in result if item["skill_id"] == "7")["metrics"] == {"usage_count": 2}
    assert next(item for item in result if item["skill_id"] == "9")["metrics"] is None
    assert query.skill_metric_value({"metrics": None}) is None
