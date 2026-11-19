# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read exact scoped physical metrics and source-backed scalar summaries in ES."""

from nexent.storage.errors import InvalidInput, ScopeDenied, Unavailable
from nexent.storage.models import (
    VectorCollectionStatistics,
    VectorFieldStatistics,
    VectorSummaryField,
)

# Paths are parameters. No consumer-supplied code or field name enters this script.
SCALAR_SOURCE = """
for (def path : params.paths) {
    def value = params._source;
    boolean found = true;
    for (def part : path) {
        if (!(value instanceof Map) || !value.containsKey(part)) { found = false; break; }
        value = value[part];
    }
    if (!found) { continue; }
    def pending = new ArrayList(); pending.add(value);
    def seen = new HashSet();
    while (!pending.isEmpty()) {
        def item = pending.remove(pending.size() - 1);
        if (item == null) { continue; }
        if (item instanceof List) { pending.addAll(item); continue; }
        if (item instanceof Map) { throw new IllegalArgumentException('Expected a scalar summary value'); }
        def text = item.toString();
        if (seen.add(text)) { emit(text); }
    }
    break;
}
"""


def _fields(binding, fields):
    if (not isinstance(fields, tuple) or len(fields) > 10
        or any(not isinstance(field, VectorSummaryField) for field in fields)
        or len({field.name for field in fields}) != len(fields)):
        raise InvalidInput()
    for field in fields:
        for path in field.paths:
            root = binding.schema.get(path[0])
            if (root is None or path[0] in (binding.text_field, *binding.additional_text_fields)
                or len(path) > 1 and root.kind != 'object'
                or len(path) == 1 and root.kind not in {'string', 'integer', 'number', 'boolean'}):
                raise InvalidInput()
    runtime, aggs = {}, {}
    for index, field in enumerate(fields):
        name = f'si_summary_{index}'
        runtime[name] = {'type': 'keyword', 'script': {'source': SCALAR_SOURCE,
            'params': {'paths': [['payload', *path] for path in field.paths]}}}
        aggs[f's{index}'] = {'cardinality': {'field': name}}
        aggs[f't{index}'] = {'terms': {'field': name, 'size': 10, 'order': [{'_count': 'desc'}, {'_key': 'asc'}]}}
    return {'size': 0, 'runtime_mappings': runtime, 'aggs': aggs}


def _integer(value, *, cardinality=False):
    if type(value) is int and value >= 0:
        return value
    if cardinality and type(value) is float and value >= 0 and value.is_integer():
        return int(value)
    raise ValueError('Invalid statistic')


def _summaries(result, fields):
    summaries = []
    for index, field in enumerate(fields):
        aggs = result['aggregations']
        distinct = _integer(aggs[f's{index}']['value'], cardinality=True)
        buckets = aggs[f't{index}']['buckets']
        if not isinstance(buckets, list) or len(buckets) > 10:
            raise ValueError('Invalid summary')
        values = []
        for bucket in buckets:
            key = bucket['key']
            _integer(bucket['doc_count'])
            if not isinstance(key, str) or key in values:
                raise ValueError('Invalid summary')
            values.append(key)
        if len(values) > distinct:
            raise ValueError('Invalid summary')
        summaries.append(VectorFieldStatistics(field.name, distinct, tuple(values)))
    return tuple(summaries)


def _complete(result, context, *, search=False):
    try:
        failed = result['_shards']['failed']
        if type(failed) is not int or failed != 0 or search and result['timed_out'] is not False:
            raise ValueError('Incomplete statistics')
    except (KeyError, TypeError, ValueError):
        raise Unavailable(operation_id=context.operation_id) from None


def collection_statistics(store, collection, fields, *, context):
    binding = store._binding(collection, maintenance=True)
    if not binding.owns_collection:
        raise ScopeDenied()
    query = _fields(binding, fields)
    query['query'] = store._filter(binding, None)
    with store._client(context) as client:
        stats = store._call(client, 'indices.stats', context, index=binding.index)
        _complete(stats, context)
        settings = store._call(client, 'indices.get_settings', context, index=binding.index)
        result = store._call(client, 'search', context, index=binding.index, body=query,
                             allow_partial_search_results=False) if fields else None
        if fields:
            _complete(result, context, search=True)
    try:
        primaries = stats['indices'][binding.index]['primaries']
        created = settings[binding.index]['settings']['index']['creation_date']
        if not isinstance(created, str) or not created.isascii() or not created.isdecimal():
            raise ValueError('Invalid creation time')
        answer = VectorCollectionStatistics(collection, _integer(primaries['docs']['count']),
            _integer(primaries['store']['size_in_bytes']), int(created),
            _integer(primaries['search']['query_total']), _integer(primaries['request_cache']['hit_count']),
            _summaries(result, fields))
    except (KeyError, TypeError, ValueError, OverflowError):
        raise Unavailable(operation_id=context.operation_id) from None
    context.remaining()
    return answer
