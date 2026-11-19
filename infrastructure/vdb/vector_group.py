# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped scalar groups with finite representative payload projections in ES."""

import json

from nexent.storage.errors import InvalidInput, ScopeDenied, Unavailable
from nexent.storage.models import VectorGroup, VectorGroupQuery

from infrastructure.vdb.vector_statistics import _complete, _fields, _integer


def _query(store, binding, query, where):
    if not isinstance(query, VectorGroupQuery):
        raise InvalidInput()
    query = VectorGroupQuery(query.by, query.sample_fields, query.limit)
    body = _fields(binding, (query.by,))
    includes = ["_si_tenant", "_si_collection"]
    for selected in query.sample_fields:
        _fields(binding, (selected,))
        for path in selected.paths:
            name = ".".join(("payload", *path))
            if name not in includes:
                includes.append(name)
    body["query"] = store._filter(binding, where)
    body["aggs"] = {
        "groups": {
            "terms": {
                "field": "si_summary_0",
                "size": query.limit,
                "order": [{"_count": "desc"}, {"_key": "asc"}],
            },
            "aggs": {"sample": {"top_hits": {"size": 1, "_source": includes}}},
        }
    }
    return body


def _sample(source, fields):
    result = {}
    for field in fields:
        for path in field.paths:
            value, found = source, True
            for part in ("payload", *path):
                if not isinstance(value, dict) or part not in value:
                    found = False
                    break
                value = value[part]
            if found:
                result[field.name] = value
                break
    json.dumps(result, allow_nan=False)
    return result


def collection_groups(store, collection, query, *, where, context):
    binding = store._binding(collection, maintenance=True)
    body = _query(store, binding, query, where)
    with store._client(context) as client:
        response = store._call(
            client,
            "search",
            context,
            index=binding.index,
            body=body,
            allow_partial_search_results=False,
        )
        _complete(response, context, search=True)
    try:
        buckets = response["aggregations"]["groups"]["buckets"]
        if not isinstance(buckets, list) or len(buckets) > query.limit:
            raise ValueError("Invalid groups")
        groups, keys, previous = [], set(), None
        for bucket in buckets:
            key, count = bucket["key"], _integer(bucket["doc_count"])
            if not isinstance(key, str) or key in keys or count <= 0:
                raise ValueError("Invalid group")
            order = (-count, key)
            if previous is not None and order < previous:
                raise ValueError("Unordered groups")
            previous = order
            hits = bucket["sample"]["hits"]["hits"]
            if not isinstance(hits, list) or len(hits) != 1:
                raise ValueError("Invalid representative")
            source = hits[0]["_source"]
            if (
                source["_si_tenant"] != store.scope.tenant_id
                or source["_si_collection"] != collection
            ):
                raise ScopeDenied()
            groups.append(
                VectorGroup(
                    collection, key, count, _sample(source, query.sample_fields)
                )
            )
            keys.add(key)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise Unavailable(operation_id=context.operation_id) from None
    context.remaining()
    return tuple(groups)
