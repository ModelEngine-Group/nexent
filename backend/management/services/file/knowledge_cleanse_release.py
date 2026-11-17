# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resource-authorized release retains uploader identity and never replays a delete."""

from contracts.agentos_knowledge import cleanse_output_prefix
from contracts.knowledge_cleanse import cleanse_lookup, parse_cleanse_request
from management.services.file.cleanse_cancellation import require_knowledge_cleanup
from management.services.file.cleanse_jobs import DATASET
from management.services.file.knowledge_artifact_cleanup import (
    delete_private_artifacts,
    inspect_private_artifacts,
    private_directory_absent,
)
from management.services.knowledge_base.deletion_journal import DeletionPhaseChanged
from nexent.storage.errors import Conflict, OutcomeUnknown
from nexent.storage.models import (
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)

from infrastructure.file_processing.artifacts import bind_knowledge_cleanse_artifacts

RELEASING = 'KNOWLEDGE_ARTIFACTS_DELETING'


def _patch(jobs, row, values, context):
    receipt = jobs.patch(DATASET, row['id'], FieldPatch(set_values=values), expected=Revision(str(row['revision'])), context=context)
    if receipt.outcome is not WriteOutcome.CONFIRMED:
        raise OutcomeUnknown(operation_id=context.operation_id)
    if not receipt.matched:
        raise DeletionPhaseChanged()
    updated = jobs.get(DATASET, row['id'], context=context)
    if updated is None:
        raise OutcomeUnknown(operation_id=context.operation_id)
    return updated


def release_knowledge_artifacts(jobs, resources, reference, *, user_id, context, limit):
    def authorize():
        return require_knowledge_cleanup(jobs, resources, reference, user_id=user_id, context=context, releasing=True)

    scope, cursor, released = authorize(), None, True
    while True:
        page = jobs.query(DATASET, RecordQuery(where=Junction('and', scope), order_by=(Sort('job_id'),)),
                          PageRequest(limit=100, cursor=cursor), context=context)
        for row in page.items:
            if row['execution_ended'] is not True or row['status'] not in {'completed', 'failed', 'cancelled', 'released'}:
                released = False
                continue
            if row['status'] == 'released':
                if row['artifact'] is not None or row['reconcile_required']:
                    raise Conflict()
                continue
            owner = not row['reconcile_required']
            if not owner and row['error_code'] != RELEASING:
                released = False
                continue
            request = parse_cleanse_request(row)
            selected = cleanse_lookup(row, request)
            prefix = cleanse_output_prefix(selected)
            never_started = row['attempt_id'] is None and row['artifact'] is None and owner
            if never_started:
                authorize()
                _patch(jobs, row, {'status': 'released', 'artifact': None, 'error_code': None, 'reconcile_required': False}, context)
                continue
            if row['artifact_prefix'] is None:
                released = False
                continue
            if row['artifact_prefix'] != prefix:
                raise Conflict()
            authorize()
            objects = bind_knowledge_cleanse_artifacts(jobs.scope.tenant_id, user_id, selected, request.source, context=context)
            try:
                if owner:
                    inventory = inspect_private_artifacts(objects, row, request, limit=limit, context=context)
                    authorize()
                    row = _patch(jobs, row, {'reconcile_required': True, 'error_code': RELEASING}, context)
                    absent = delete_private_artifacts(objects, inventory, prefix, context=context)
                else:
                    absent = private_directory_absent(objects, prefix, context=context)
            finally:
                objects.close()
            if not absent:
                released = False
                continue
            authorize()
            _patch(jobs, row, {'status': 'released', 'artifact': None, 'reconcile_required': False, 'error_code': None}, context)
        if page.next_cursor is None:
            return released
        cursor = page.next_cursor
