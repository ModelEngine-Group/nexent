# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-ADMIT-01/KB-FENCE-01: actual SI transactions serialize upload admission."""

from threading import Event
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from management.services.file.upload_admission import KnowledgeUploadAdmission
from management.services.knowledge_base.base_deletion import (
    request_knowledge_base_deletion,
)
from nexent.storage.errors import (
    Conflict,
    OperationCancelled,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import StorageScope, WriteOutcome, WriteReceipt

from infrastructure.rdb import knowledge_admission as mapping
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def admission(monkeypatch, resources):  # noqa: F811
    metadata = sa.MetaData()

    def clone(original, name):
        return sa.Table(name, metadata, *[
            sa.Column(c.name, sa.JSON(none_as_null=True) if isinstance(c.type, sa.JSON) else c.type,
                      primary_key=c.primary_key, nullable=c.nullable)
            for c in original.c
        ])

    knowledge, files = clone(mapping.knowledge, 'knowledge'), clone(mapping.files, 'files')
    monkeypatch.setattr(mapping, 'knowledge', knowledge)
    monkeypatch.setattr(mapping, 'files', files)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(knowledge.insert(), {'knowledge_id': 1, 'tenant_id': 'tenant-a', 'index_name': 'kb-one',
                                               'version': 3, 'delete_flag': 'N', 'created_by': 'user-a'})
    actor = SimpleNamespace(user_id='user-a', tenant_id='tenant-a')
    records = mapping.bind_admission_records(StorageScope('management', actor.tenant_id, actor.user_id, {KB, FILES}), engine)
    _, update, resource_engine, tables = resources
    authorized = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id, set(tables)), resource_engine)
    service = KnowledgeUploadAdmission(records, authorized, actor)

    def spec(file_id='a' * 32, **changes):
        return {'file_id': file_id, 'tenant_id': 'tenant-a', 'knowledge_id': 1, 'index_name': 'kb-one',
                'original_filename': file_id + '.txt', 'bucket_name': 'bucket', 'object_name': 'knowledge_base/' + file_id,
                'created_by': 'user-a', 'upload_owner_service': 'management', **changes}

    try:
        yield SimpleNamespace(**locals())
    finally:
        records.close()
        authorized.close()
        engine.dispose()


def test_batch_commits_all_files_with_one_knowledge_revision_and_existing_defaults(admission):
    s = admission
    result = s.service.admit([s.spec(), s.spec('b' * 32)], context=context())
    assert [row['file_id'] for row in result] == ['a' * 32, 'b' * 32]
    assert all(row['status'] == 'UPLOADING' and row['stage'] == 'UPLOAD' for row in result)
    assert all(row['source_generation'] == row['processing_attempt'] == 0 for row in result)
    assert all(row['created_by'] == row['updated_by'] == 'user-a' for row in result)
    assert all(row['source_revision'] is None and row['deletion_request'] is None for row in result)
    assert s.records.get(KB, 1, context=context())['version'] == 4


def test_second_file_failure_rolls_back_the_first_file_and_knowledge_revision(admission):
    s = admission
    with pytest.raises(Conflict):
        s.service.admit([s.spec(), s.spec()], context=context())
    assert s.records.get(FILES, 'a' * 32, context=context()) is None
    assert s.records.get(KB, 1, context=context())['version'] == 3


@pytest.mark.parametrize('change', [{'tenant_id': 'foreign'}, {'created_by': 'other'}, {'knowledge_id': 2}, {'index_name': 'other'}])
def test_untrusted_identity_cannot_create_any_file(admission, change):
    s = admission
    with pytest.raises(ScopeDenied):
        s.service.admit([s.spec(**change)], context=context())
    assert s.records.get(FILES, 'a' * 32, context=context()) is None
    assert s.records.get(KB, 1, context=context())['version'] == 3


def test_revoked_current_membership_blocks_admission_before_writes(admission):
    s = admission
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.service.admit([s.spec()], context=context())
    assert s.records.get(KB, 1, context=context())['version'] == 3


def test_deletion_wins_and_later_upload_is_rejected_even_with_a_stale_resource_read(admission):
    s = admission
    row = request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    assert row['deletion_request']['user_id'] == 'user-a'
    with pytest.raises(Conflict):
        s.service.admit([s.spec()], context=context())
    assert s.records.get(FILES, 'a' * 32, context=context()) is None
    assert s.records.get(KB, 1, context=context()) == row


def test_upload_wins_and_deletion_keeps_the_original_inflight_guard(admission):
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException

    s = admission
    s.service.admit([s.spec()], context=context())
    with pytest.raises(AppException) as raised:
        request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    assert raised.value.error_code == ErrorCode.KNOWLEDGE_DELETE_BLOCKED
    assert raised.value.details['blocking_files'][0]['file_id'] == 'a' * 32
    current = s.records.get(KB, 1, context=context())
    assert current['deletion_request'] is None and current['version'] == 4


@pytest.mark.parametrize('status,stage', [('DELETE_REQUESTED', 'DELETE_RUNTIME_PENDING'), ('COMPLETED', 'DELETE_SOURCE_DELETING')])
def test_incomplete_file_deletion_must_not_lose_its_knowledge_authorization(admission, status, stage):
    s = admission
    s.service.admit([s.spec()], context=context())
    with s.engine.begin() as connection:
        connection.execute(s.files.update().values(status=status, stage=stage, deletion_request={'scope': 'full'}))
    from contracts.errors.exceptions import AppException

    with pytest.raises(AppException):
        request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    assert s.records.get(KB, 1, context=context())['deletion_request'] is None


def test_existing_deletion_intent_remains_owned_by_the_original_actor(admission):
    s = admission
    original = request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    assert request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context()) == original
    assert s.records.get(KB, 1, context=context())['version'] == 4


def test_empty_batch_does_not_touch_any_revision(admission):
    assert admission.service.admit([], context=context()) == []
    assert admission.records.get(KB, 1, context=context())['version'] == 3


@pytest.mark.parametrize('outcome', [WriteOutcome.UNKNOWN, WriteOutcome.CONFIRMED])
def test_unknown_or_unmatched_parent_update_is_not_retried_and_cannot_create_files(admission, monkeypatch, outcome):
    s = admission
    original = type(s.records).patch
    calls = []

    def patch(self, dataset, *args, **kwargs):
        calls.append(dataset)
        receipt = original(self, dataset, *args, **kwargs)
        return WriteReceipt(receipt.operation_id, False, receipt.revision, outcome)

    monkeypatch.setattr(type(s.records), 'patch', patch)
    with pytest.raises(OutcomeUnknown if outcome is WriteOutcome.UNKNOWN else Conflict):
        s.service.admit([s.spec()], context=context())
    assert calls == [KB]
    assert s.records.get(FILES, 'a' * 32, context=context()) is None
    assert s.records.get(KB, 1, context=context())['version'] == 3


def test_cancel_after_insert_rolls_back_instead_of_committing_late(admission, monkeypatch):
    from dataclasses import replace

    s = admission
    stopped = Event()
    operation = replace(context(), cancelled=stopped)
    create = type(s.records).create

    def cancel_after_insert(self, *args, **kwargs):
        row = create(self, *args, **kwargs)
        stopped.set()
        return row

    monkeypatch.setattr(type(s.records), 'create', cancel_after_insert)
    with pytest.raises(OperationCancelled):
        s.service.admit([s.spec()], context=operation)
    assert s.records.get(KB, 1, context=context())['version'] == 3
    assert s.records.get(FILES, 'a' * 32, context=context()) is None


@pytest.mark.parametrize('injected', [{'version': 100}, {'updated_by': 'other'}, {'deletion_request': {}}, {'source_generation': 2}])
def test_upload_spec_cannot_assign_lifecycle_control_or_audit_fields(admission, injected):
    from pydantic import ValidationError

    s = admission
    with pytest.raises(ValidationError):
        s.service.admit([s.spec(**injected)], context=context())
    assert s.records.get(KB, 1, context=context())['version'] == 3
    assert s.records.get(FILES, 'a' * 32, context=context()) is None


def test_stale_parent_revision_does_not_reject_another_valid_upload(admission, monkeypatch):
    s = admission
    s.service.admit([s.spec()], context=context())
    get = type(s.records).get
    captured = []

    def stale_once(self, dataset, *args, **kwargs):
        row = get(self, dataset, *args, **kwargs)
        if dataset == KB and not captured:
            captured.append(row['version'])
            return {**row, 'version': 3}
        return row

    monkeypatch.setattr(type(s.records), 'get', stale_once)
    result = s.service.admit([s.spec('b' * 32)], context=context())
    assert result[0]['file_id'] == 'b' * 32 and captured == [4]
    assert s.records.get(KB, 1, context=context())['version'] == 5
    assert s.records.get(FILES, 'a' * 32, context=context()) is not None
    assert s.records.get(FILES, 'b' * 32, context=context()) is not None


def test_upload_outcome_updates_only_the_admitted_owner_and_status(admission):
    from management.services.file.upload_admission import _patch_upload_record

    s = admission
    [row] = s.service.admit([s.spec()], context=context())
    args = (s.records, row["file_id"])
    foreign = SimpleNamespace(user_id="user-b", tenant_id="tenant-a")
    fields = {"status": "UPLOADED", "uploaded_at": "2026-09-01T12:00:00+00:00"}
    assert _patch_upload_record(*args, foreign, ("UPLOADING",), fields, context=context()) is None
    assert _patch_upload_record(*args, s.actor, ("FAILED",), fields, context=context()) is None

    updated = _patch_upload_record(*args, s.actor, ("UPLOADING",), fields, context=context())
    assert updated["version"] == row["version"] + 1 and updated["status"] == "UPLOADED"
    assert updated["uploaded_at"] == fields["uploaded_at"] and updated["updated_by"] == s.actor.user_id
    assert _patch_upload_record(*args, s.actor, ("UPLOADING",), {"status": "FAILED"}, context=context()) is None
    renamed = _patch_upload_record(*args, s.actor, ("UPLOADED",), {"original_filename": "new.txt"}, context=context())
    assert renamed["original_filename"] == "new.txt" and renamed["uploaded_at"] == fields["uploaded_at"]


@pytest.mark.parametrize("outcome", [WriteOutcome.CONFIRMED, WriteOutcome.UNKNOWN])
def test_upload_outcome_cas_never_replays_an_unconfirmed_update(admission, monkeypatch, outcome):
    from unittest.mock import Mock

    from management.services.file.upload_admission import _patch_upload_record

    s = admission
    [row] = s.service.admit([s.spec()], context=context())
    patch_record = Mock(return_value=WriteReceipt("op", False, outcome=outcome))
    monkeypatch.setattr(type(s.records), "patch", patch_record)
    args = (s.records, row["file_id"], s.actor, ("UPLOADING",), {"status": "FAILED"})
    if outcome is WriteOutcome.UNKNOWN:
        with pytest.raises(OutcomeUnknown):
            _patch_upload_record(*args, context=context())
    else:
        assert _patch_upload_record(*args, context=context()) is None
    patch_record.assert_called_once()
    assert patch_record.call_args.kwargs["expected"].value == str(row["version"])
