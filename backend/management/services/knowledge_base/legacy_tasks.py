# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Inspect attributable legacy tasks without claiming a Redis snapshot or replaying work."""

import hashlib
import re

from contracts.knowledge_maintenance import (
    INSPECTION_FILES,
    LEGACY_TASKS,
    LegacyTaskFinding,
    LegacyTaskPage,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, Sort

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.legacy_tasks import legacy_task_records
from infrastructure.source_inspection import source_inspection_ports

TASK_FIELDS = ('process_task_id', 'forward_task_id', 'parent_task_id')


def _scope(port, actor):
    if (port.scope.system or port.scope.service_role != 'management' or port.scope.actor_id != actor.user_id
        or port.scope.tenant_id != actor.tenant_id): raise ScopeDenied()


def _files(records, context, page_size):
    rows, cursor = [], None
    while True:
        page = records.query(INSPECTION_FILES, RecordQuery(order_by=(Sort('file_id'),)),
            PageRequest(limit=page_size, cursor=cursor), context=context)
        rows.extend(page.items)
        cursor = page.next_cursor
        if cursor is None: return rows


def _finding(row, file_ids):
    item = LegacyTaskFinding(task_id_hash=hashlib.sha256(row['task_id'].encode()).hexdigest(), origin=row['origin'],
        status=row['status'], revision=row['revision'], file_id=row['file_id'], auxiliary_present=row['auxiliary_present'])
    if not row['result_present']: item.issues.append('LEGACY_RESULT_MISSING')
    elif not row['metadata_valid']: item.issues.append('LEGACY_METADATA_INVALID')
    if row['index_matches'] is False: item.issues.append('LEGACY_TASK_INDEX_CONFLICT')
    if row['tenant_matches'] is False: item.issues.append('LEGACY_TASK_TENANT_CONFLICT')
    if row['status'] not in {'SUCCESS', 'FAILURE', 'REVOKED'}: item.issues.append('LEGACY_TASK_NOT_TERMINAL')
    if not file_ids: item.issues.append('REDIS_ONLY_TASK')
    elif len(file_ids) > 1: item.issues.append('LEGACY_TASK_FILE_AMBIGUOUS')
    elif row['file_id'] is not None and row['file_id'] not in file_ids: item.issues.append('LEGACY_TASK_FILE_CONFLICT')
    return item


class LegacyTaskInspector:
    def __init__(self, *, ports=source_inspection_ports, tasks=legacy_task_records, cancellation_scope=None):
        self.ports, self.tasks, self.cancellation_scope = ports, tasks, cancellation_scope

    def scan(self, knowledge_id, actor, emit, *, page_size=100, context):
        if type(knowledge_id) is not int or knowledge_id <= 0: raise InvalidInput()
        PageRequest(limit=page_size)
        with self.ports(actor, knowledge_id, context=context) as (files, resources):
            _scope(files, actor); _scope(resources, actor)
            authorize = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
            knowledge = authorize.resolve_knowledge(knowledge_id, edit=True, context=context)
            if knowledge['knowledge_sources'] != 'elasticsearch': raise ScopeDenied()
            baseline = _files(files, context, page_size)
            references, invalid = {}, 0
            for row in baseline:
                if (row['tenant_id'] != actor.tenant_id or row['knowledge_id'] != knowledge_id
                    or row['index_name'] != knowledge['index_name']): raise ScopeDenied()
                for name in TASK_FIELDS:
                    task_id = row[name]
                    if task_id is None: continue
                    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
                        invalid += 1; continue
                    references.setdefault(task_id, set()).add(row['file_id'])
            revision = knowledge_search_revision(knowledge)
            seen, count, issues, redis_only = set(), 0, 0, 0
            def check():
                if authorize.resolve_knowledge(knowledge_id, edit=True, context=context) != knowledge: raise Conflict()
                if _files(files, context, page_size) != baseline: raise Conflict()
                context.remaining()
            def output(rows):
                nonlocal count, issues, redis_only
                findings = []
                for row in rows:
                    if row['task_id'] in seen: continue
                    seen.add(row['task_id'])
                    item = _finding(row, references.get(row['task_id'], set()))
                    findings.append(item); count += 1; issues += bool(item.issues); redis_only += not bool(references.get(row['task_id']))
                check()
                emit(LegacyTaskPage(knowledge_id=knowledge_id, index_name=knowledge['index_name'], tenant_id=actor.tenant_id,
                    actor_id=actor.user_id, knowledge_revision=revision, tasks=findings))
            with self.tasks(actor, knowledge_id, knowledge['index_name'], known_tasks=set(references), context=context,
                            cancellation_scope=self.cancellation_scope) as tasks:
                _scope(tasks, actor)
                keys = sorted(references)
                for offset in range(0, len(keys), page_size):
                    output([tasks.get(LEGACY_TASKS, key, context=context) for key in keys[offset:offset+page_size]])
                cursor = None
                while True:
                    page = tasks.query(LEGACY_TASKS, RecordQuery(), PageRequest(limit=page_size, cursor=cursor), context=context)
                    output(page.items)
                    cursor = page.next_cursor
                    if cursor is None: break
            check()
            return {'tasks': count, 'tasks_with_issues': issues, 'redis_only_tasks': redis_only,
                'invalid_pg_task_references': invalid, 'knowledge_revision': revision, 'snapshot': False}
