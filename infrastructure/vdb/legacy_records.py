# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact legacy collection reads through RecordStore; native PITs never escape the port."""

import asyncio
import base64
import hashlib
import json
import re
from contextlib import contextmanager
from threading import Lock
from time import monotonic
from uuid import uuid4

from contracts.knowledge_maintenance import LEGACY_DOCUMENTS as DOCS
from contracts.knowledge_maintenance import LEGACY_FILE_CHUNK_FIELDS
from contracts.knowledge_maintenance import LEGACY_VECTOR_METADATA as META
from elastic_transport import TransportError
from elasticsearch import ApiError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    NotFound,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    CapabilitySet,
    OperationContext,
    Page,
    PageRequest,
    ReadConsistency,
    RecordQuery,
)

from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

SOURCE_FIELDS = ('path_or_url', 'embedding', 'tenant_id', 'created_by', *LEGACY_FILE_CHUNK_FIELDS)
PIT_FIELDS = (*SOURCE_FIELDS, *(f'metadata.{field}' for field in (*LEGACY_FILE_CHUNK_FIELDS, 'tenant_id')))


class LegacyVectorRecords:
    capabilities = CapabilitySet(frozenset({'record.get', 'record.query', 'record.count'}))

    def __init__(self, scope, collection, client_factory, *, cancellation_scope=None):
        if not isinstance(collection, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', collection):
            raise InvalidInput()
        if scope.system or scope.resource_prefix or scope.service_role != 'management' or scope.namespaces != {DOCS, META}:
            raise ScopeDenied()
        self.scope, self._collection, self._factory = scope, collection, client_factory
        self._cancellation = cancellation_scope
        self._pit, self._meta, self._total, self._closed = None, None, None, False
        self._index_uuid = None
        self._nonce = uuid4().hex
        self._catalog = DatasetCatalog((
            DatasetDefinition(DOCS, 'document_id', (FieldDefinition('document_id', 'string'), FieldDefinition('tenant_id', 'string'),
                FieldDefinition('revision', 'string'), FieldDefinition('properties', 'object')),
                frozenset({'management'}), tenant_field='tenant_id'),
            DatasetDefinition(META, 'collection', (FieldDefinition('collection', 'string'), FieldDefinition('tenant_id', 'string'),
                FieldDefinition('revision', 'string'), FieldDefinition('dimensions', 'integer', nullable=True),
                FieldDefinition('metric', 'string', nullable=True)), frozenset({'management'}), tenant_field='tenant_id'),
        ))

    def _query(self, dataset, query):
        if self._closed:
            raise ScopeDenied()
        self._catalog.authorize(dataset, self.scope)
        if not isinstance(query, RecordQuery):
            raise InvalidInput()
        if query.where is not None or query.order_by:
            raise CapabilityUnsupported()
        return self._catalog.query(dataset, self.scope, query).fields

    @contextmanager
    def _client(self, context):
        try: asyncio.get_running_loop()
        except RuntimeError: pass
        else: raise CapabilityUnsupported()
        client = self._factory(context.remaining())
        closed, lock = False, Lock()
        def close():
            nonlocal closed
            with lock:
                if closed: return
                closed = True
            client.close()
        scope = self._cancellation
        token = scope.register_closer(close) if scope is not None and context.cancelled is scope.stop_event else None
        try: yield client
        finally:
            if token is not None: scope.unregister_closer(token)
            close()

    def _read(self, method, context, **kwargs):
        with self._client(context) as client:
            target = client.options(request_timeout=min(5, context.remaining()), max_retries=0, retry_on_timeout=False)
            for name in method.split('.'): target = getattr(target, name)
            try:
                result = target(**kwargs)
            except ApiError as error:
                kind = {404: NotFound, 409: Conflict, 401: ScopeDenied, 403: ScopeDenied}.get(error.status_code, Unavailable)
                raise kind(operation_id=context.operation_id) from None
            except (TransportError, OSError):
                raise Unavailable(operation_id=context.operation_id) from None
        result = result.body if hasattr(result, 'body') else result
        if not isinstance(result, dict):
            raise Unavailable()
        return result

    def _metadata(self, context):
        if self._meta is None:
            mapping = self._read('indices.get_mapping', context, index=self._collection)
            settings = self._read('indices.get_settings', context, index=self._collection, name='index.uuid')
            if set(mapping) != {self._collection} or set(settings) != {self._collection}:
                raise ScopeDenied()
            try:
                schema = mapping[self._collection]['mappings']
                vector = schema.get('properties', {}).get('embedding', {})
                identity = settings[self._collection]['settings']['index']['uuid']
                if not isinstance(identity, str) or not identity or not isinstance(vector, dict): raise ValueError()
                dimension = vector.get('dims') if vector.get('type') == 'dense_vector' else None
                if dimension is not None and (type(dimension) is not int or dimension <= 0): raise ValueError()
                metric = vector.get('similarity') if dimension is not None else None
                if metric is not None and not isinstance(metric, str): raise ValueError()
                revision = hashlib.sha256(json.dumps([identity, schema], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            except (KeyError, TypeError, ValueError, AttributeError):
                raise Unavailable() from None
            self._meta = {'collection': self._collection, 'tenant_id': self.scope.tenant_id,
                          'revision': revision, 'dimensions': dimension, 'metric': metric}
            self._index_uuid = identity
        context.remaining()
        return self._meta

    def get(self, dataset, key, *, fields=(), consistency=ReadConsistency.AUTHORITATIVE, context):
        fields = self._query(dataset, RecordQuery(fields=fields))
        if consistency != ReadConsistency.AUTHORITATIVE:
            raise CapabilityUnsupported()
        if dataset == DOCS:
            return self._document(key, fields, context)
        if key != self._collection:
            return None
        return {name: self._metadata(context)[name] for name in fields}

    def _check_index(self, context):
        current = self._read('indices.get_settings', context, index=self._collection, name='index.uuid')
        if set(current) != {self._collection}:
            raise ScopeDenied()
        try:
            identity = current[self._collection]['settings']['index']['uuid']
        except (KeyError, TypeError):
            raise Unavailable() from None
        if identity != self._index_uuid:
            raise Conflict()

    def _document(self, key, fields, context):
        if not isinstance(key, str) or not key or len(key.encode('utf-8')) > 512:
            raise InvalidInput()
        self._metadata(context)
        try:
            hit = self._read('get', context, index=self._collection, id=key)
        except NotFound:
            self._check_index(context)
            return None
        if hit.get('_index') != self._collection or hit.get('_id') != key:
            raise ScopeDenied()
        self._check_index(context)
        context.remaining()
        seq, term, source = hit.get('_seq_no'), hit.get('_primary_term'), hit.get('_source')
        if (hit.get('found') is not True or not isinstance(source, dict)
            or type(seq) is not int or seq < 0 or type(term) is not int or term < 1):
            raise Unavailable()
        row = {'document_id': key, 'tenant_id': self.scope.tenant_id, 'revision': f'{seq}:{term}',
               'properties': source}
        return {name: row[name] for name in fields}

    def _search(self, size, context, *, after=None):
        self._metadata(context)
        if self._pit is None:
            opened = self._read('open_point_in_time', context, index=self._collection, keep_alive='1m', allow_partial_search_results=False)
            if not isinstance(opened.get('id'), str) or not opened['id']: raise Unavailable()
            self._pit = opened['id']
            # Opening a PIT must not silently follow a deleted/recreated index or a replacement alias.
            self._check_index(context)
        context.remaining()
        body = {'pit': {'id': self._pit, 'keep_alive': '1m'}, 'size': size, 'query': {'match_all': {}},
                'sort': [{'_shard_doc': 'asc'}], '_source': list(PIT_FIELDS), 'track_total_hits': True,
                'seq_no_primary_term': True}
        if after is not None: body['search_after'] = [after]
        result = self._read('search', context, body=body, allow_partial_search_results=False)
        if isinstance(result.get('pit_id'), str) and result['pit_id']: self._pit = result['pit_id']
        try:
            total = result['hits']['total']
            if (result.get('timed_out') is not False or result['_shards']['failed'] != 0 or total['relation'] != 'eq'
                or type(result['_shards']['failed']) is not int
                or type(total['value']) is not int or total['value'] < 0 or not isinstance(result['hits']['hits'], list)
                or len(result['hits']['hits']) > size):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise Unavailable() from None
        if self._total is not None and self._total != total['value']: raise Conflict()
        self._total = total['value']
        context.remaining()
        return result['hits']['hits']

    def query(self, dataset, query, page, *, context):
        fields = self._query(dataset, query)
        if not isinstance(page, PageRequest): raise InvalidInput()
        if dataset == META:
            if page.cursor is not None: raise InvalidInput()
            return Page((self.get(META, self._collection, fields=fields, context=context),))
        identity = hashlib.sha256(json.dumps([self.scope.tenant_id, self.scope.actor_id, self._collection,
            self._nonce, self._metadata(context)['revision'], fields], separators=(',', ':')).encode()).hexdigest()
        after = None
        if page.cursor is not None:
            try:
                if not isinstance(page.cursor, str) or len(page.cursor) > 4096: raise ValueError()
                data = json.loads(base64.b64decode(page.cursor, altchars=b'-_', validate=True))
                if (not isinstance(data, dict) or set(data) != {'binding', 'after'} or data['binding'] != identity
                    or type(data['after']) is not int or data['after'] < 0): raise ValueError()
                after = data['after']
            except (ValueError, TypeError, UnicodeError):
                raise InvalidInput() from None
        hits = self._search(page.limit + 1, context, after=after)
        if len(hits) > page.limit + 1: raise Unavailable()
        rows, previous = [], after if after is not None else -1
        for hit in hits:
            try:
                position = hit['sort']
                if (not isinstance(position, list) or len(position) != 1 or type(position[0]) is not int or position[0] <= previous
                    or not isinstance(hit['_id'], str) or not hit['_id'] or len(hit['_id']) > 512 or not isinstance(hit['_source'], dict)
                    or type(hit['_seq_no']) is not int or hit['_seq_no'] < 0
                    or type(hit['_primary_term']) is not int or hit['_primary_term'] < 1): raise ValueError()
                previous = position[0]
                row = {'document_id': hit['_id'], 'tenant_id': self.scope.tenant_id,
                       'revision': f"{hit['_seq_no']}:{hit['_primary_term']}",
                       'properties': {name: hit['_source'][name] for name in (*SOURCE_FIELDS, 'metadata') if name in hit['_source']}}
                rows.append({name: row[name] for name in fields})
            except (KeyError, ValueError, TypeError):
                raise Unavailable() from None
        cursor = base64.urlsafe_b64encode(json.dumps({'binding': identity, 'after': hits[page.limit-1]['sort'][0]},
            separators=(',', ':')).encode()).decode() if len(hits) > page.limit else None
        return Page(tuple(rows[:page.limit]), cursor)

    def count(self, dataset, query, *, context):
        self._query(dataset, query)
        if dataset == META: return int(self.get(META, self._collection, context=context) is not None)
        self._search(0, context)
        return self._total

    @staticmethod
    def _deny(*args, **kwargs):
        raise ScopeDenied()

    create = patch = delete = claim = increment = sum = sum_by = _deny

    def transaction(self, *, context):
        raise CapabilityUnsupported()

    def close(self):
        if self._closed: return
        self._closed = True
        if self._pit is not None:
            context = OperationContext('legacy-vector-close-' + self._nonce, monotonic() + 5)
            result = self._read('close_point_in_time', context, id=self._pit)
            if result.get('succeeded') is not True: raise Unavailable()
