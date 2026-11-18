# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Match an operator's private archive against current, scoped legacy RecordStore reads."""

import hashlib
import json
from pathlib import Path

from contracts.knowledge_maintenance import LEGACY_TASKS, LegacyTaskArchivePage
from management.services.knowledge_base.legacy_tasks import _finding, _scope
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied


def task_references(row):
    return {name: row[name] for name in ('process_task_id', 'forward_task_id', 'parent_task_id') if row.get(name) is not None}


def _load(path, row, resource, actor, context):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024 * 1024: raise InvalidInput()
    expected = {hashlib.sha256(value.encode()).hexdigest() for value in task_references(row).values()}
    digest, selected, seen = hashlib.sha256(), {}, set()
    started, finished, count, read_bytes = None, False, 0, 0
    with path.open('rb') as stream:
        while raw := stream.readline(128 * 1024 * 1024 + 1):
            context.remaining()
            read_bytes += len(raw)
            if len(raw) > 128 * 1024 * 1024 or read_bytes > 1024 * 1024 * 1024 or finished: raise InvalidInput()
            digest.update(raw)
            try: record = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError): raise InvalidInput() from None
            if not isinstance(record, dict): raise InvalidInput()
            if started is None:
                if (record.get('kind') != 'legacy_task_archive_inventory_start' or record.get('legacy_quiesced') is not True
                    or not isinstance(record.get('operation_id'), str) or not record['operation_id']): raise InvalidInput()
                if (record.get('tenant_id') != actor.tenant_id or record.get('actor_id') != actor.user_id
                    or record.get('knowledge_id') != row['knowledge_id']): raise ScopeDenied()
                started = record
            elif record.get('kind') == 'legacy_task_archive_page':
                page = LegacyTaskArchivePage.model_validate({key: value for key, value in record.items() if key != 'kind'})
                if (page.tenant_id != actor.tenant_id or page.actor_id != actor.user_id or page.knowledge_id != row['knowledge_id']
                    or page.index_name != resource.collection): raise ScopeDenied()
                if page.knowledge_revision != resource.revision: raise Conflict()
                for task in page.tasks:
                    if task.task_id_hash in seen: raise InvalidInput()
                    seen.add(task.task_id_hash); count += 1
                    if task.task_id_hash in expected:
                        if (task.origin != 'pg_reference' or task.issues or task.status not in {'SUCCESS', 'FAILURE', 'REVOKED'}
                            or task.file_id is not None and task.file_id != row['file_id']): raise Conflict()
                        selected[task.task_id_hash] = task
            elif (record.get('kind') == 'legacy_task_archive_inventory_finished'
                and record.get('operation_id') == started['operation_id'] and record.get('scan_complete') is True
                and record.get('snapshot') is False and record.get('migration_ready') is False
                and record.get('knowledge_revision') == resource.revision and record.get('tasks') == count):
                finished = True
            else: raise InvalidInput()
    if not finished or set(selected) != expected: raise InvalidInput()
    return digest.hexdigest(), selected


def _values(task):
    values = {}
    for value in task.archive:
        key = (value.binding, value.key)
        if key in values: raise InvalidInput()
        values[key] = (value.encoding, value.sha256, value.value_base64)
    return values


def verify_task_archive(path, row, resource, actor, *, task_records, context, cancellation_scope=None, expected_hash=None):
    digest, archived = _load(path, row, resource, actor, context)
    if expected_hash is not None and digest != expected_hash: raise Conflict()
    references = set(task_references(row).values())
    with task_records(actor, row['knowledge_id'], resource.collection, known_tasks=references, context=context,
                      cancellation_scope=cancellation_scope) as records:
        _scope(records, actor)
        for task_id in sorted(references):
            context.remaining()
            current = _finding(records.get(LEGACY_TASKS, task_id, fields=('archive',), context=context), {row['file_id']})
            saved = archived[hashlib.sha256(task_id.encode()).hexdigest()]
            if (current.model_dump(exclude={'archive'}) != saved.model_dump(exclude={'archive'})
                or _values(current) != _values(saved)): raise Conflict()
    context.remaining()
    return digest
