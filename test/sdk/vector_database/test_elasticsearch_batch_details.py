# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Batch transport equivalence, bounded calls and partial failure recovery."""

from unittest.mock import MagicMock

import pytest
from elasticsearch import Elasticsearch

from nexent.vector_database.elasticsearch_core import ElasticSearchCore


def build_core(count=2):
    core = ElasticSearchCore.__new__(ElasticSearchCore)
    core.client = MagicMock()
    names = [f"kb-{i}" for i in range(count)]
    stats = {"indices": {name: {"primaries": {
        "docs": {"count": 200}, "store": {"size_in_bytes": 4096},
        "search": {"query_total": 8}, "request_cache": {"hit_count": 2},
    }, "total": {"store": {"size_in_bytes": 8192}}} for name in names}}
    settings = {name: {"settings": {"index": {"creation_date": "123"}}} for name in names}
    aggregation = {"aggregations": {
        "unique_path_or_url_count": {"value": 7},
        "process_sources": {"buckets": [{"key": "file"}]},
        "embedding_models": {"buckets": [{"key": "embedding"}]},
    }}
    core.client.indices.stats.return_value = stats
    core.client.indices.get_settings.return_value = settings
    core.client.search.return_value = aggregation
    core.client.msearch.return_value = {"responses": [aggregation for _ in names]}
    return core, names


@pytest.mark.parametrize("count", [2, 20, 100])
def test_batch_equals_serial_with_three_transport_calls(count):
    core, names = build_core(count)
    expected = core._get_indices_detail_serial(names, 1536)
    core.client.reset_mock()
    assert core.get_indices_detail(names, 1536) == expected
    core.client.indices.stats.assert_called_once_with(index=names)
    core.client.indices.get_settings.assert_called_once_with(index=names)
    core.client.msearch.assert_called_once()
    core.client.search.assert_not_called()
    body = core.client.msearch.call_args.kwargs["body"]
    assert len(body) == 2 * count
    assert body[1]["aggs"]["unique_path_or_url_count"] == {"cardinality": {"field": "path_or_url"}}
    assert expected[names[0]]["base_info"]["doc_count"] == 7
    assert expected[names[0]]["base_info"]["chunk_count"] == 200


def test_partial_msearch_failure_retries_only_failed_index():
    core, names = build_core()
    expected = core._get_indices_detail_serial(names)
    core.client.reset_mock()
    core.client.msearch.return_value["responses"][1] = {"error": {"type": "unavailable"}}
    assert core.get_indices_detail(names) == expected
    core.client.search.assert_called_once_with(index=names[1], body=core.client.search.call_args.kwargs["body"])
    assert core.client.indices.stats.call_count == 2


def test_transport_failure_retains_per_index_errors():
    core, names = build_core()
    core.client.indices.stats.side_effect = lambda *, index: (
        core.client.indices.stats.return_value if isinstance(index, str) else (_ for _ in ()).throw(RuntimeError("bulk"))
    )
    core.client.search.side_effect = lambda *, index, body: (
        core.client.search.return_value if index == names[0] else (_ for _ in ()).throw(RuntimeError("missing index"))
    )
    result = core.get_indices_detail(names)
    assert result[names[0]]["base_info"]["doc_count"] == 7
    assert result[names[1]] == {"error": "missing index"}


def test_empty_and_single_index_avoid_unnecessary_batching():
    core, names = build_core(1)
    assert core.get_indices_detail([]) == {}
    core.client.indices.stats.assert_not_called()
    assert core.get_indices_detail(names)[names[0]]["base_info"]["embedding_dim"] == 1024
    core.client.msearch.assert_not_called()


def test_incomplete_batch_response_uses_original_error_boundary():
    core, names = build_core()
    expected = core._get_indices_detail_serial(names)
    core.client.reset_mock()
    core.client.msearch.return_value = {"responses": []}
    assert core.get_indices_detail(names) == expected
    assert core.client.search.call_count == 2


def test_real_client_builds_multi_index_paths_and_msearch_body(mocker):
    core, names = build_core()
    stats = core.client.indices.stats.return_value
    settings = core.client.indices.get_settings.return_value
    responses = core.client.msearch.return_value
    client = Elasticsearch("http://localhost:9200")
    core.client = client
    requests = []

    def perform(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path.endswith("/_stats"):
            return stats
        if path.endswith("/_settings"):
            return settings
        return responses

    mocker.patch.object(client, "perform_request", side_effect=perform)
    try:
        assert len(core.get_indices_detail(names)) == 2
    finally:
        client.close()
    assert [(method, path) for method, path, _ in requests] == [
        ("GET", "/kb-0,kb-1/_stats"), ("GET", "/kb-0,kb-1/_settings"), ("POST", "/_msearch"),
    ]
    body = requests[2][2]["body"]
    assert body[0] == {"index": "kb-0"}
    assert body[2] == {"index": "kb-1"}
    assert requests[2][2]["headers"]["content-type"] == "application/x-ndjson"
