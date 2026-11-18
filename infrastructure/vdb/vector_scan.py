# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped vector keyset reads without inference, provider cursors or retries."""

import base64
import hashlib
import json
from dataclasses import asdict

from nexent.storage.errors import InvalidInput, Unavailable
from nexent.storage.models import Page, PageRequest, VectorRecord

from infrastructure.vdb.vector_schema import vector


def _after(cursor, fingerprint):
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > 16384:
        raise InvalidInput()
    try:
        data = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
        if (not isinstance(data, dict) or set(data) != {'query', 'after'}
            or data['query'] != fingerprint or not isinstance(data['after'], str)
            or not data['after'] or len(data['after']) > 1024):
            raise InvalidInput()
    except (ValueError, UnicodeError):
        raise InvalidInput() from None
    return data['after']


def scan_vectors(store, binding, where, page, *, context, include_vector=True):
    if not isinstance(page, PageRequest):
        raise InvalidInput()
    query = store._filter(binding, where)
    read_schema = asdict(binding)
    # Payload edit policy does not alter the established read cursor contract.
    read_schema.pop('mutable_fields')
    fingerprint = hashlib.sha256(json.dumps(
        [store.scope.service_role, store.scope.tenant_id, store.scope.actor_id, read_schema, query, include_vector],
        sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode()).hexdigest()
    after = _after(page.cursor, fingerprint)
    options = {
        'index': binding.index, 'query': query, 'size': page.limit + 1,
        'sort': [{'_si_key': 'asc'}],
        'source': ['_si_tenant', '_si_collection', '_si_key', '_si_generation'] + (['embedding'] if include_vector else [])
                  + ['payload.' + name for name in binding.schema],
    }
    if after is not None:
        options['search_after'] = [after]
    with store._client(context) as client:
        result = store._call(client, 'search', context, **options)
    result = result.body if hasattr(result, 'body') else result
    if not isinstance(result, dict):
        raise Unavailable(operation_id=context.operation_id)
    shards, hits = result.get('_shards', {}), result.get('hits')
    if (result.get('timed_out') or not isinstance(shards, dict) or shards.get('failed', 0)
        or not isinstance(hits, dict)):
        raise Unavailable(operation_id=context.operation_id)
    hits = hits.get('hits')
    if not isinstance(hits, list) or len(hits) > page.limit + 1:
        raise Unavailable(operation_id=context.operation_id)
    records, previous = [], after
    for hit in hits:
        if not isinstance(hit, dict):
            raise Unavailable(operation_id=context.operation_id)
        source = hit.get('_source')
        try:
            key, data, generation = store._decode(binding, source)
            record = VectorRecord(key, vector(binding, source.get('embedding')) if include_vector else (), data, generation)
        except InvalidInput:
            raise Unavailable(operation_id=context.operation_id) from None
        if previous is not None and key.key <= previous:
            raise Unavailable(operation_id=context.operation_id)
        records.append(record)
        previous = key.key
    cursor = None
    if len(records) > page.limit:
        cursor = base64.urlsafe_b64encode(json.dumps(
            {'query': fingerprint, 'after': records[page.limit - 1].key.key},
            separators=(',', ':'),
        ).encode()).decode()
    return Page(tuple(records[:page.limit]), cursor)
