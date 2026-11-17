# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finalize physically deleted KB metadata in a single scoped RecordStore transaction."""

import base64
import json
from copy import deepcopy

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_base_deletion import KnowledgeBaseDeleteAuthorization
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_CONVERSATIONS as CONVERSATIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_ASSIGNMENTS as TAGS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_PROJECTIONS as PROJECTIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TOOL_BINDINGS as TOOLS,
)
from management.services.knowledge_base.admission import (
    change_knowledge_admission,
    require_admission_actor,
)
from management.services.knowledge_base.base_deletion import (
    KnowledgeBaseDeletionJournal,
)
from management.services.knowledge_base.base_deletion_authorization import (
    authorize_base_deletion,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, OutcomeUnknown
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)


def _rows(records, dataset, keys, *, context, where=None):
    """Use keyset pages so this transaction may remove earlier rows safely."""
    last = None
    while True:
        terms = [where] if where is not None else []
        if last is not None:
            after = []
            for position, key in enumerate(keys):
                after.append(Junction('and', (
                    *(Comparison(previous, 'eq', last[previous]) for previous in keys[:position]),
                    Comparison(key, 'gt', last[key]),
                )))
            terms.append(Junction('or', tuple(after)))
        page = records.query(dataset, RecordQuery(
            where=Junction('and', tuple(terms)) if terms else None, order_by=tuple(Sort(key) for key in keys),
        ), PageRequest(limit=200), context=context)
        yield from page.items
        if len(page.items) < 200:
            return
        last = page.items[-1]


def _confirmed(receipt, context, *, delete=False):
    if receipt.outcome is WriteOutcome.UNKNOWN:
        raise OutcomeUnknown(operation_id=context.operation_id)
    if receipt.outcome is not WriteOutcome.CONFIRMED or not (receipt.deleted if delete else receipt.matched):
        raise Conflict()


def _locked(records, dataset, key, context):
    # Empty audited UPDATE obtains the row lock before reading the value to merge.
    _confirmed(records.patch(dataset, key, FieldPatch(set_values={}), context=context), context)
    row = records.get(dataset, key, context=context)
    if row is None:
        raise Conflict()
    return row


def _local_scope(scope, knowledge_id):
    if scope is None:
        return None
    updated = deepcopy(scope)
    local = updated['local']
    kept = [value for value in local['knowledge_ids'] if value != str(knowledge_id)]
    if kept != local['knowledge_ids']:
        local['knowledge_ids'] = kept
        if not kept:
            local['mode'] = 'disabled'
    return updated


def _conversation_patch(row, knowledge_id):
    scope = _local_scope(row['knowledge_scope'], knowledge_id)
    workbench = row['workbench_config']
    if workbench is not None:
        workbench = {**workbench, 'knowledge_scope': _local_scope(workbench['knowledge_scope'], knowledge_id)}
    values = {}
    if scope != row['knowledge_scope']:
        values['knowledge_scope'] = scope
    if workbench != row['workbench_config']:
        values['workbench_config'] = workbench
    return FieldPatch(set_values=values, increments={'workbench_config_version': 1} if 'workbench_config' in values else {})


def _document_matches(resource_id, index_name):
    try:
        value = json.loads(base64.urlsafe_b64decode(resource_id.encode('ascii')).decode('utf-8'))
    except (UnicodeError, ValueError):
        return False
    return isinstance(value, list) and len(value) == 3 and str(value[0]) == 'local' and str(value[1]) == index_name


def _remove_bindings(records, row, context):
    counts = {'tool_bindings_updated': 0, 'conversations_updated': 0}
    for tool in _rows(records, TOOLS, ('tool_instance_id', 'version_no'), context=context):
        if (not isinstance(tool['params'], dict) or not isinstance(tool['params'].get('index_names'), list)
                or row['index_name'] not in tool['params']['index_names']):
            continue
        key = tool['tool_instance_id'], tool['version_no']
        current = _locked(records, TOOLS, key, context)
        if not isinstance(current['params'], dict) or not isinstance(current['params'].get('index_names'), list):
            continue
        params = deepcopy(current['params'])
        params['index_names'] = [value for value in params['index_names'] if value != row['index_name']]
        if params != current['params']:
            _confirmed(records.patch(TOOLS, key, FieldPatch(set_values={'params': params}), context=context), context)
            counts['tool_bindings_updated'] += 1
    for conversation in _rows(records, CONVERSATIONS, ('conversation_id',), context=context):
        selected = _conversation_patch(conversation, row['knowledge_id'])
        if not selected.set_values:
            continue
        key = conversation['conversation_id']
        current = _locked(records, CONVERSATIONS, key, context)
        patch = _conversation_patch(current, row['knowledge_id'])
        if patch.set_values:
            _confirmed(records.patch(CONVERSATIONS, key, patch, context=context), context)
            counts['conversations_updated'] += 1
    return counts


def remove_knowledge_metadata_bindings(records, row, *, context):
    """Remove only this scoped catalog's bindings, local tags and projection ledger."""
    counts = _remove_bindings(records, row, context)
    counts.update(tag_assignments_deleted=0, tag_projections_deleted=0)
    for tag in _rows(records, TAGS, ('assignment_id',), context=context,
                     where=Comparison('resource_type', 'in', ['knowledge_base', 'knowledge_document'])):
        selected = tag['resource_id'] == row['index_name'] if tag['resource_type'] == 'knowledge_base' else (
            _document_matches(tag['resource_id'], row['index_name']))
        if selected:
            _confirmed(records.delete(TAGS, tag['assignment_id'], context=context), context, delete=True)
            counts['tag_assignments_deleted'] += 1
    for projection in _rows(records, PROJECTIONS, ('projection_id',), context=context, where=Junction('and', (
        Comparison('provider', 'eq', 'local'), Comparison('knowledge_base_id', 'eq', row['index_name']),
    ))):
        _confirmed(records.delete(PROJECTIONS, projection['projection_id'], context=context), context, delete=True)
        counts['tag_projections_deleted'] += 1
    return counts


def finalize_knowledge_base_deletion(records, resources, previous, actor, *, context):
    require_admission_actor(records, resources, actor)
    journal = KnowledgeBaseDeletionJournal(records, resources, actor)
    if journal.intent(previous).phase != 'metadata_pending':
        raise Conflict()
    current = journal.load(previous['knowledge_id'], context=context)
    if current['version'] != previous['version'] or journal.intent(current).phase != 'metadata_pending':
        raise Conflict()
    with records.transaction(context=context) as transaction:
        # The same parent row serializes upload admission and all finalization owners.
        row = change_knowledge_admission(transaction, current, {}, expected=Revision(str(current['version'])), context=context)
        authorize_base_deletion(transaction, resources, KnowledgeBaseDeleteAuthorization(knowledge_id=row['knowledge_id']),
                                actor, context=context)
        counts = remove_knowledge_metadata_bindings(transaction, row, context=context)
        counts['files_deleted'] = 0
        sources = set()
        for file in _rows(transaction, FILES, ('file_id',), context=context,
                          where=Comparison('knowledge_id', 'eq', row['knowledge_id'])):
            if file['source_key'] is not None:
                sources.add((file['source_space'], file['source_key'], file['source_revision']))
            _confirmed(transaction.delete(FILES, file['file_id'], expected=Revision(str(file['version'])), context=context),
                        context, delete=True)
            counts['files_deleted'] += 1
        counts['source_objects_deleted'] = len(sources)
        KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve_knowledge(
            row['knowledge_id'], edit=True, cleanup=True, context=context,
        )
        intent = journal.intent(row).model_copy(update={'phase': 'deleted'})
        row = change_knowledge_admission(transaction, row, {'deletion_request': intent.model_dump(mode='json')},
                                         expected=Revision(str(row['version'])), context=context)
        _confirmed(transaction.delete(KB, row['knowledge_id'], expected=Revision(str(row['version'])), context=context),
                    context, delete=True)
        result = {**row, 'delete_flag': 'Y', 'metadata_cleanup': counts}
    return result
