# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-INFRA-DPR-GROUP-01 prove bounded neutral aggregation and scoped samples."""

from copy import deepcopy

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied, Unavailable
from nexent.storage.models import Comparison, VectorGroupQuery, VectorSummaryField

from test.backend.infrastructure.test_vector_statistics import (
    boundary as boundary,  # noqa: PLC0414
)
from test.backend.infrastructure.test_vector_statistics import context, summary


def query():
    return VectorGroupQuery(
        summary(), (VectorSummaryField("name", (("location", "filename"),)),), 2
    )


def result():
    def bucket(key, count, name):
        return {
            "key": key,
            "doc_count": count,
            "sample": {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "_si_tenant": "tenant-a",
                                "_si_collection": "kb",
                                "payload": {"location": {"filename": name}},
                            }
                        }
                    ]
                }
            },
        }

    return {
        "_shards": {"failed": 0},
        "timed_out": False,
        "aggregations": {
            "groups": {
                "buckets": [bucket("one", 3, ["raw", None]), bucket("two", 1, None)]
            }
        },
    }


def test_group_preserves_json_samples_and_uses_only_selected_scoped_fields(boundary):
    port, client, _ = boundary
    client.search.return_value = result()
    values = port.group(
        "kb", query(), where=Comparison("filename", "is_null", False), context=context()
    )
    assert [(v.collection, v.key, v.count, v.sample) for v in values] == [
        ("kb", "one", 3, {"name": ["raw", None]}),
        ("kb", "two", 1, {"name": None}),
    ]
    call = client.search.call_args.kwargs
    body = call["body"]
    assert (
        call["index"] == "owned-index" and call["allow_partial_search_results"] is False
    )
    assert body["aggs"]["groups"]["terms"] == {
        "field": "si_summary_0",
        "size": 2,
        "order": [{"_count": "desc"}, {"_key": "asc"}],
    }
    assert body["aggs"]["groups"]["aggs"]["sample"]["top_hits"]["_source"] == [
        "_si_tenant",
        "_si_collection",
        "payload.location.filename",
    ]
    assert body["query"]["bool"]["filter"][:2] == [
        {"term": {"_si_tenant": "tenant-a"}},
        {"term": {"_si_collection": "kb"}},
    ]
    assert "embedding" not in str(body) and "payload.content" not in str(body)
    assert "vector.group" in port.capabilities.supported
    assert (
        client.options.call_count == 1
        and client.options.call_args.kwargs["max_retries"] == 0
    )
    client.close.assert_called_once()
    client.indices.stats.assert_not_called()
    client.bulk.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "timeout",
        "shard",
        "duplicate",
        "empty-hit",
        "wrong-count",
        "wrong-order",
        "foreign",
    ],
)
def test_incomplete_or_wrong_scope_groups_never_become_empty_success(boundary, change):
    port, client, _ = boundary
    data = deepcopy(result())
    buckets = data["aggregations"]["groups"]["buckets"]
    if change == "timeout":
        data["timed_out"] = True
    elif change == "shard":
        data["_shards"]["failed"] = 1
    elif change == "duplicate":
        buckets[1]["key"] = "one"
    elif change == "empty-hit":
        buckets[0]["sample"]["hits"]["hits"] = []
    elif change == "wrong-count":
        buckets[0]["doc_count"] = True
    elif change == "wrong-order":
        buckets.reverse()
    else:
        buckets[0]["sample"]["hits"]["hits"][0]["_source"]["_si_tenant"] = "foreign"
    client.search.return_value = data
    with pytest.raises(ScopeDenied if change == "foreign" else Unavailable):
        port.group("kb", query(), context=context())
    client.close.assert_called_once()


@pytest.mark.parametrize("limit", [0, True, 1001])
def test_group_limit_is_finite(limit):
    with pytest.raises(InvalidInput):
        VectorGroupQuery(summary(), (), limit)


def test_body_field_and_ungranted_collection_fail_before_provider(boundary):
    port, _client, factory = boundary
    with pytest.raises(InvalidInput):
        port.group(
            "kb",
            VectorGroupQuery(VectorSummaryField("body", (("content",),))),
            context=context(),
        )
    with pytest.raises(ScopeDenied):
        port.group("other", query(), context=context())
    factory.assert_not_called()
