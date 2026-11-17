# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The existing KB revision orders upload admission and deletion intent."""

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import FieldPatch, WriteOutcome


def require_admission_actor(records, resources, actor):
    if any(port.scope.system or port.scope.service_role != 'management'
           or port.scope.actor_id != actor.user_id or port.scope.tenant_id != actor.tenant_id
           for port in (records, resources)):
        raise ScopeDenied()


def change_knowledge_admission(records, row, values, *, expected, context):
    receipt = records.patch(KB, row['knowledge_id'], FieldPatch(set_values=values),
                            expected=expected, context=context)
    if receipt.outcome is WriteOutcome.UNKNOWN:
        raise OutcomeUnknown(operation_id=context.operation_id)
    if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
        raise Conflict()
    current = records.get(KB, row['knowledge_id'], context=context)
    if current is None:
        raise OutcomeUnknown(operation_id=context.operation_id)
    return current
