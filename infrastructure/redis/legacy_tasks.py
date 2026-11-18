# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only RecordStore projection of legacy task results and auxiliary key presence."""

import asyncio
import hashlib
import json
import re
from collections import deque
from contextlib import contextmanager
from threading import Lock
from uuid import uuid4

from contracts.knowledge_maintenance import LEGACY_TASKS
from nexent.storage.errors import (
    CapabilityUnsupported,
    InvalidInput,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    CapabilitySet,
    Page,
    PageRequest,
    ReadConsistency,
    RecordQuery,
)

from infrastructure.redis.kv import RedisKeyValueConfig, _make_client

STATUSES = {'PENDING', 'RECEIVED', 'STARTED', 'RETRY', 'SUCCESS', 'FAILURE', 'REVOKED'}
TASK_ID = re.compile(r'[A-Za-z0-9_-]{1,100}')


class LegacyTaskRecords:
    capabilities = CapabilitySet(frozenset({'record.get', 'record.query'}))

    def __init__(self, scope, index_name, known_tasks, *, backend_url, general_url, client_factory=None, cancellation_scope=None):
        if scope.system or scope.resource_prefix or scope.service_role != 'management' or scope.namespaces != {LEGACY_TASKS}:
            raise ScopeDenied()
        if not isinstance(index_name, str) or not index_name or len(index_name) > 100:
            raise InvalidInput()
        self.scope, self._index = scope, index_name
        self._known = frozenset(known_tasks)
        if any(not isinstance(key, str) or not TASK_ID.fullmatch(key) for key in self._known):
            raise InvalidInput()
        self._configs = {kind: RedisKeyValueConfig(url, kind) for kind, url in [('backend', backend_url), ('general', general_url)]}
        self._factory = client_factory or _make_client
        self._cancellation = cancellation_scope
        self._buffer, self._scan, self._next, self._closed = deque(), 0, None, False
        self._started, self._finished = False, False

    def _authorize(self, dataset, *, fields=(), consistency=ReadConsistency.AUTHORITATIVE):
        if self._closed or dataset != LEGACY_TASKS: raise ScopeDenied()
        if fields or consistency != ReadConsistency.AUTHORITATIVE: raise CapabilityUnsupported()

    @contextmanager
    def _client(self, kind, context):
        try: asyncio.get_running_loop()
        except RuntimeError: pass
        else: raise CapabilityUnsupported()
        from redis.backoff import NoBackoff
        from redis.exceptions import RedisError
        from redis.retry import Retry

        config = self._configs[kind]
        timeout = min(context.remaining(), config.request_timeout)
        client = self._factory(config.url, decode_responses=False, socket_timeout=timeout, socket_connect_timeout=timeout,
            retry=Retry(NoBackoff(), 0), retry_on_timeout=False, retry_on_error=[], context=context)
        closed, lock = False, Lock()
        def once():
            nonlocal closed
            with lock:
                if closed: return
                closed = True
            client.close()
        scope = self._cancellation
        token = scope.register_closer(once) if scope is not None and context.cancelled is scope.stop_event else None
        try:
            context.remaining()
            yield client
            context.remaining()
        except (RedisError, OSError):
            context.remaining()
            raise Unavailable(operation_id=context.operation_id) from None
        finally:
            if token is not None: scope.unregister_closer(token)
            once()

    def _result(self, client, task_id, context):
        context.remaining()
        raw = client.get('celery-task-meta-' + task_id)
        valid, payload, result = False, {}, {}
        if raw is not None and not isinstance(raw, bytes): raise Unavailable()
        if raw is not None and len(raw) <= 1024 * 1024:
            try:
                payload = json.loads(raw)
                valid = isinstance(payload, dict) and payload.get('status') in STATUSES
                if not isinstance(payload, dict): payload = {}
                result = payload.get('result')
                if not isinstance(result, dict): result = {}
            except (ValueError, UnicodeError, RecursionError, TypeError):
                payload, result = {}, {}
        index, tenant = result.get('index_name'), result.get('tenant_id')
        file_id = result.get('file_id')
        return {'task_id': task_id, 'status': payload['status'] if valid else 'UNKNOWN',
            'revision': hashlib.sha256(raw or b'').hexdigest(), 'result_present': raw is not None, 'metadata_valid': valid,
            'index_matches': None if index is None else index == self._index,
            'tenant_matches': None if tenant is None else tenant == self.scope.tenant_id,
            'file_id': file_id if isinstance(file_id, str) and re.fullmatch(r'[0-9a-f]{32}', file_id) else None,
            'origin': 'pg_reference' if task_id in self._known else 'index_metadata'}

    def _auxiliary(self, row, context):
        task_id = row['task_id']; present = []
        with self._client('general', context) as client:
            for name, key in [('progress', 'progress:' + task_id), ('error', 'error:reason:' + task_id),
                              ('cancel', 'cancel:' + task_id), ('chunks', 'dp:' + task_id + ':chunks')]:
                context.remaining()
                count = client.exists(key)
                if type(count) is not int or count not in {0, 1}: raise Unavailable()
                if count: present.append(name)
            cursor = 0
            while True:
                context.remaining()
                cursor, keys = self._scan_keys(client, cursor, 'dp:' + task_id + ':part:*', context)
                if keys:
                    present.append('parts'); break
                if not cursor: break
        row['auxiliary_present'] = present
        return row

    @staticmethod
    def _scan_keys(client, cursor, pattern, context):
        response = client.scan(cursor=cursor, match=pattern, count=100)
        context.remaining()
        if (not isinstance(response, (tuple, list)) or len(response) != 2 or type(response[0]) is not int
            or response[0] < 0 or not isinstance(response[1], (tuple, list)) or len(response[1]) > 10000
            or any(not isinstance(key, bytes) for key in response[1])):
            raise Unavailable()
        return response

    def get(self, dataset, key, *, fields=(), consistency=ReadConsistency.AUTHORITATIVE, context):
        self._authorize(dataset, fields=fields, consistency=consistency)
        if key not in self._known: raise ScopeDenied()
        with self._client('backend', context) as client: row = self._result(client, key, context)
        return self._auxiliary(row, context)

    def query(self, dataset, query, page, *, context):
        self._authorize(dataset)
        if not isinstance(query, RecordQuery) or not isinstance(page, PageRequest): raise InvalidInput()
        if query.where is not None or query.order_by or query.fields: raise CapabilityUnsupported()
        if self._finished or page.cursor != self._next or (self._started and page.cursor is None): raise InvalidInput()
        self._started = True
        selected = []
        with self._client('backend', context) as client:
            while len(selected) < page.limit:
                if not self._buffer:
                    self._scan, keys = self._scan_keys(client, self._scan, 'celery-task-meta-*', context)
                    self._buffer.extend(keys)
                while self._buffer and len(selected) < page.limit:
                    try: task_id = self._buffer.popleft().decode('ascii').removeprefix('celery-task-meta-')
                    except UnicodeError: continue
                    if not TASK_ID.fullmatch(task_id): continue
                    row = self._result(client, task_id, context)
                    if row['index_matches'] is True: selected.append(row)
                if not self._buffer and not self._scan: break
        self._finished = not self._buffer and not self._scan
        self._next = None if self._finished else uuid4().hex
        return Page(tuple(self._auxiliary(row, context) for row in selected), self._next)

    def close(self):
        if self._closed: return
        self._closed = True

    def _unsupported(self, *args, **kwargs): raise CapabilityUnsupported()
    insert = update = delete = count = transaction = _unsupported
