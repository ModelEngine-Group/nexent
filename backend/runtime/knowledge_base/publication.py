# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared published-manifest and writer-completion checks for read-only KB operations."""

from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery, Sort

from infrastructure.rdb.knowledge_jobs import FILES, JOBS


def published_files(records, knowledge_id, *, context):
    after = None
    while True:
        terms = [Comparison('knowledge_id', 'eq', knowledge_id)]
        if after is not None: terms.append(Comparison('record_id', 'gt', after))
        page = records.query(FILES, RecordQuery(where=Junction('and', tuple(terms)),
            order_by=(Sort('record_id'),)), PageRequest(limit=500), context=context)
        for row in page.items:
            context.remaining()
            if row['knowledge_id'] != knowledge_id or row['tenant_id'] != records.scope.tenant_id: raise ScopeDenied()
            key = row['record_id']
            if after is not None and key <= after: raise Conflict()
            after = key
            version = row['visible_version']
            if version is None or version <= row['tombstone_version']: continue
            if not row['visible_generation'] or not row['visible_job_id']: raise Conflict()
            yield row
        if len(page.items) < 500: return


def published_job(records, resource, manifest, *, context):
    job = records.get(JOBS, manifest['visible_job_id'], context=context)
    if (job is None or job['operation'] != 'upload' or job['status'] != 'completed'
        or job['knowledge_id'] != resource.knowledge_id or job['file_id'] != manifest['file_id']
        or job['file_version'] != manifest['visible_version'] or not job['writer_ended']
        or job['reconcile_required'] or job['attempt_id'] != manifest['visible_generation']
        or type(job['chunk_count']) is not int or job['chunk_count'] < 0): raise Conflict()
    return job
