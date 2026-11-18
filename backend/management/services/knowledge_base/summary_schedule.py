# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Summary-specific CAS admission and publication; failed versions are never replayed."""

from datetime import UTC, datetime
from uuid import uuid4

from contracts.constants.constants import VALID_SUMMARY_FREQUENCIES
from contracts.knowledge_summary import (
    SUMMARY_DATASET,
    SummaryAttempt,
    SummarySchedule,
    SummaryWork,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)


class SummaryScheduleJournal:
    def __init__(self, records, *, authorize, clock=lambda: datetime.now(UTC)):
        scope = records.scope
        if scope.system or scope.service_role != 'management' or SUMMARY_DATASET not in scope.namespaces:
            raise ScopeDenied()
        self.records, self.authorize, self.clock = records, authorize, clock

    def record(self, knowledge_id, *, context):
        row = self.records.get(SUMMARY_DATASET, knowledge_id, context=context)
        if row is None:
            raise NotFound()
        return row

    def prepare(self, knowledge_id, *, context):
        """Read an enabled schedule only after verifying its actual issuer's current edit grant."""
        row = self.record(knowledge_id, context=context)
        if row['summary_frequency'] is None or row['summary_schedule'] is None:
            return None
        self._schedule(row)
        self._grant(row, context)
        return row

    @staticmethod
    def _patch(port, row, values, context):
        result = port.patch(SUMMARY_DATASET, row['knowledge_id'], FieldPatch(set_values=values),
                            expected=Revision(str(row['version'])), context=context)
        if result.outcome == WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if result.outcome != WriteOutcome.CONFIRMED or not result.matched:
            raise Conflict()
        return port.get(SUMMARY_DATASET, row['knowledge_id'], context=context)

    def _lock(self, port, knowledge_id, context, *, expected=None):
        row = port.get(SUMMARY_DATASET, knowledge_id, context=context)
        if row is None:
            raise NotFound()
        if expected is not None and row['version'] != expected:
            raise Conflict()
        return self._patch(port, row, {}, context)

    def _grant(self, row, context):
        grant = self.authorize(row, context=context)
        if (row['tenant_id'] != self.records.scope.tenant_id or row.get('deletion_request') is not None
            or grant.knowledge_id != row['knowledge_id'] or grant.collection != row['index_name']):
            raise ScopeDenied()
        return grant

    def configure(self, index_name, frequency, *, context):
        with self.records.transaction(context=context) as tx:
            page = tx.query(SUMMARY_DATASET, RecordQuery(where=Comparison('index_name', 'eq', index_name)),
                            PageRequest(limit=2), context=context)
            if not page.items:
                raise NotFound()
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            row = self._lock(tx, page.items[0]['knowledge_id'], context, expected=page.items[0]['version'])
            self._grant(row, context)
            if frequency not in VALID_SUMMARY_FREQUENCIES:
                raise InvalidInput()
            old = SummarySchedule.model_validate(row['summary_schedule']) if row['summary_schedule'] is not None else None
            schedule = SummarySchedule(user_id=self.records.scope.actor_id, configuration_id=uuid4().hex,
                                       attempt=old.attempt if old else None)
            return self._patch(tx, row, {'summary_frequency': frequency, 'summary_schedule': schedule.model_dump(mode='json')}, context)

    def _schedule(self, row):
        if row['summary_frequency'] is None or row['summary_frequency'] not in VALID_SUMMARY_FREQUENCIES or row['summary_schedule'] is None:
            raise Conflict()
        schedule = SummarySchedule.model_validate(row['summary_schedule'])
        if schedule.user_id != self.records.scope.actor_id:
            raise ScopeDenied()
        return schedule

    def admit(self, snapshot, *, data_revision, knowledge_revision, model_id, context):
        with self.records.transaction(context=context) as tx:
            row = tx.get(SUMMARY_DATASET, snapshot['knowledge_id'], context=context)
            if row is None:
                raise NotFound()
            if row['version'] != snapshot['version']:
                raise Conflict()
            schedule = self._schedule(row)
            if (row['knowledge_sources'] != 'elasticsearch' or type(row['embedding_model_id']) is not int
                or row['embedding_model_id'] <= 0):
                raise ScopeDenied()
            grant = self._grant(row, context)
            if grant.revision != knowledge_revision:
                raise Conflict()
            if schedule.attempt and schedule.attempt.data_revision == data_revision:
                return None
            row = self._lock(tx, snapshot['knowledge_id'], context, expected=snapshot['version'])
            schedule = self._schedule(row)
            if self._grant(row, context).revision != knowledge_revision:
                raise Conflict()
            attempt = SummaryAttempt(attempt_id=uuid4().hex, user_id=schedule.user_id, data_revision=data_revision,
                                     knowledge_revision=knowledge_revision, model_id=model_id, started_at=self.clock().isoformat())
            saved = schedule.model_copy(update={'attempt': attempt})
            self._patch(tx, row, {'summary_schedule': saved.model_dump(mode='json')}, context)
            return SummaryWork(**saved.model_dump(), knowledge_id=row['knowledge_id'], index_name=row['index_name'])

    def _match(self, row, handle, *, active=True):
        if not isinstance(handle, SummaryWork) or handle.user_id != self.records.scope.actor_id:
            raise ScopeDenied()
        if row['summary_schedule'] is None:
            raise Conflict()
        current = SummarySchedule.model_validate(row['summary_schedule'])
        if (current.configuration_id != handle.configuration_id or current.user_id != handle.user_id
            or current.attempt != handle.attempt or row['index_name'] != handle.index_name
            or handle.attempt.user_id != handle.user_id or handle.attempt.status != 'admitted'
            or active and row['summary_frequency'] is None):
            raise Conflict()
        return current

    def complete(self, handle, summary, *, data_revision, model_id, context):
        if not isinstance(handle, SummaryWork):
            raise ScopeDenied()
        if not isinstance(summary, str) or len(summary) > 3000:
            raise InvalidInput()
        if data_revision != handle.attempt.data_revision or model_id != handle.attempt.model_id:
            raise Conflict()
        with self.records.transaction(context=context) as tx:
            row = self._lock(tx, handle.knowledge_id, context)
            current = self._match(row, handle)
            if self._grant(row, context).revision != handle.attempt.knowledge_revision:
                raise Conflict()
            now = self.clock().isoformat()
            attempt = SummaryAttempt.model_validate({**current.attempt.model_dump(), 'status': 'completed', 'completed_at': now})
            saved = current.model_copy(update={'attempt': attempt})
            return self._patch(tx, row, {'knowledge_describe': summary, 'last_summary_time': now,
                                        'summary_schedule': saved.model_dump(mode='json')}, context)

    def fail(self, handle, *, error_code, context):
        if not isinstance(handle, SummaryWork):
            raise ScopeDenied()
        with self.records.transaction(context=context) as tx:
            row = tx.get(SUMMARY_DATASET, handle.knowledge_id, context=context)
            if row is None:
                return False
            try:
                self._match(row, handle, active=False)
            except Conflict:
                return False
            row = self._lock(tx, handle.knowledge_id, context, expected=row['version'])
            current = self._match(row, handle, active=False)
            attempt = SummaryAttempt.model_validate({**current.attempt.model_dump(), 'status': 'failed',
                'completed_at': self.clock().isoformat(), 'error_code': error_code})
            saved = current.model_copy(update={'attempt': attempt})
            self._patch(tx, row, {'summary_schedule': saved.model_dump(mode='json')}, context)
            return True
