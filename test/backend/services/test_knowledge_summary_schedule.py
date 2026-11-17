# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable summary authorization and version admission use actual scoped SI transactions."""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from contracts.knowledge_summary import SUMMARY_DATASET, SummarySchedule
from management.services.knowledge_base.summary_schedule import SummaryScheduleJournal
from management.services.knowledge_base.summary_settings import (
    authorized_summary_journal,
)
from nexent.storage.errors import Conflict, NotFound, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.rdb import knowledge_summary as mapping
from infrastructure.rdb.knowledge_deletion_metadata import _LocalWallTime
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def isolated_connections(monkeypatch, tmp_path):
    original = sa.create_engine
    def engine(url, **kwargs):
        assert url == 'sqlite://'
        return original('sqlite:///' + (tmp_path / 'summary.db').as_posix(), poolclass=sa.pool.QueuePool,
                        pool_size=2, max_overflow=0, **kwargs)
    monkeypatch.setattr(sa, 'create_engine', engine)


@pytest.fixture
def setup(isolated_connections, resources, monkeypatch):
    authorize, update, engine, tables = resources
    table = tables['cleanse_knowledge']
    additions = [sa.Column('version', sa.Integer, nullable=False, server_default='0'),
        sa.Column('summary_schedule', sa.JSON), sa.Column('summary_frequency', sa.String(10)),
        sa.Column('last_summary_time', _LocalWallTime()), sa.Column('last_doc_update_time', _LocalWallTime()),
        sa.Column('knowledge_describe', sa.String(3000)), sa.Column('create_time', sa.DateTime),
        sa.Column('update_time', sa.DateTime), sa.Column('updated_by', sa.String(100))]
    with engine.begin() as connection:
        for column in additions:
            table.append_column(column)
            connection.exec_driver_sql('ALTER TABLE cleanse_knowledge ADD COLUMN ' + str(sa.schema.CreateColumn(column).compile(dialect=engine.dialect)))
    monkeypatch.setattr(mapping, 'knowledge', table)
    update('cleanse_knowledge', embedding_model_id=2)
    resources_port = authorize().records
    records = mapping.bind_summary_records(StorageScope('management', 'tenant-a', 'user-a', {SUMMARY_DATASET}), engine)
    journal = authorized_summary_journal(records, resources_port)
    yield journal, records, update, engine, table
    records.close(); resources_port.close()


def enabled(setup):
    journal, _, _, _, _ = setup
    row = journal.configure('kb-one', '3h', context=context())
    assert row['summary_frequency'] == '3h'
    return row


def admit(setup, *, revision='a'*64):
    journal = setup[0]
    row = journal.record(1, context=context())
    return journal.admit(row, data_revision=revision, knowledge_revision=knowledge_search_revision(row), model_id=5, context=context())


def test_configure_records_actual_issuer_and_new_epoch(setup):
    row = enabled(setup)
    schedule = SummarySchedule.model_validate(row['summary_schedule'])
    assert schedule.user_id == row['updated_by'] == 'user-a'
    assert schedule.attempt is None and len(schedule.configuration_id) == 32
    changed = setup[0].configure('kb-one', '1d', context=context())
    assert changed['summary_schedule']['configuration_id'] != schedule.configuration_id


@pytest.mark.parametrize('dataset,values', [
    ('cleanse_knowledge', {'created_by':'other', 'ingroup_permission':'READ_ONLY'}),
    ('cleanse_memberships', {'delete_flag':'Y'}),
    ('cleanse_knowledge', {'deletion_request':{'pending':True}}),
])
def test_configuration_requires_current_edit_dac(setup, dataset, values):
    setup[2](dataset, **values)
    with pytest.raises(ScopeDenied):
        enabled(setup)
    assert setup[0].record(1, context=context())['summary_schedule'] is None


def test_current_data_version_is_admitted_once_including_failed_and_restarted_work(setup):
    enabled(setup)
    handle = admit(setup)
    assert handle.attempt.status == 'admitted'
    before = setup[0].record(1, context=context())['version']
    assert admit(setup) is None
    assert setup[0].record(1, context=context())['version'] == before
    setup[0].fail(handle, error_code='MODEL_FAILED', context=context())
    assert admit(setup) is None
    next_handle = admit(setup, revision='b'*64)
    assert next_handle.attempt.attempt_id != handle.attempt.attempt_id
    assert next_handle.attempt.data_revision == 'b'*64


def test_reconfiguration_and_disable_preserve_version_fence(setup):
    enabled(setup)
    handle = admit(setup)
    disabled = setup[0].configure('kb-one', None, context=context())
    assert disabled['summary_frequency'] is None
    assert disabled['summary_schedule']['attempt']['data_revision'] == 'a'*64
    setup[0].configure('kb-one', '1d', context=context())
    assert admit(setup) is None
    with pytest.raises(Conflict):
        setup[0].complete(handle, 'stale', data_revision='a'*64, model_id=5, context=context())


def test_complete_updates_summary_time_and_outcome_in_one_transaction(setup):
    enabled(setup); handle = admit(setup)
    result = setup[0].complete(handle, 'actual summary', data_revision='a'*64, model_id=5, context=context())
    assert result['knowledge_describe'] == 'actual summary' and result['last_summary_time']
    assert result['summary_schedule']['attempt']['status'] == 'completed'
    assert result['updated_by'] == 'user-a'
    assert datetime.fromisoformat(result['last_summary_time']).tzinfo == UTC


@pytest.mark.parametrize('change', ['revision', 'model', 'disabled', 'revoked'])
def test_stale_or_revoked_work_cannot_publish_summary(setup, change):
    enabled(setup); handle = admit(setup)
    if change == 'disabled': setup[0].configure('kb-one', None, context=context())
    elif change == 'revoked': setup[2]('cleanse_memberships', delete_flag='Y')
    with pytest.raises((ScopeDenied, Conflict)):
        setup[0].complete(handle, 'must not publish', data_revision='b'*64 if change=='revision' else 'a'*64,
                          model_id=6 if change=='model' else 5, context=context())
    assert setup[0].record(1, context=context())['knowledge_describe'] is None


def test_old_attempt_cannot_replace_new_admission_or_result(setup):
    enabled(setup); old = admit(setup); current = admit(setup, revision='b'*64)
    assert not setup[0].fail(old, error_code='OLD_FAILURE', context=context())
    with pytest.raises(Conflict):
        setup[0].complete(old, 'old', data_revision='a'*64, model_id=5, context=context())
    setup[0].complete(current, 'current', data_revision='b'*64, model_id=5, context=context())
    assert setup[0].record(1, context=context())['knowledge_describe'] == 'current'


def test_legacy_configuration_never_borrows_created_by_identity(setup):
    setup[2]('cleanse_knowledge', summary_frequency='3h')
    with pytest.raises(Conflict): admit(setup)


@pytest.mark.parametrize('values', [{'embedding_model_id':None},{'embedding_model_id':0}])
def test_settings_remain_editable_before_execution_models_are_ready(setup, values):
    setup[2]('cleanse_knowledge', **values)
    row=setup[0].configure('kb-one','3h',context=context())
    assert row['summary_frequency']=='3h' and row['summary_schedule']['user_id']=='user-a'
    with pytest.raises(ScopeDenied):admit(setup)
    row=setup[0].configure('kb-one',None,context=context())
    assert row['summary_frequency'] is None


def test_datamate_configuration_keeps_existing_edit_denial(setup):
    setup[2]('cleanse_knowledge',knowledge_sources='datamate')
    with pytest.raises(ScopeDenied):setup[0].configure('kb-one','3h',context=context())
    assert setup[0].record(1,context=context())['summary_schedule'] is None


def test_failure_may_close_only_original_attempt_after_actor_revocation(setup):
    enabled(setup); handle = admit(setup)
    setup[2]('cleanse_memberships', delete_flag='Y')
    assert setup[0].fail(handle, error_code='AUTH_REVOKED', context=context())
    row = setup[0].record(1, context=context())
    assert row['summary_schedule']['attempt']['status'] == 'failed'
    assert row['knowledge_describe'] is None


def test_cross_tenant_reads_and_duplicate_writes_are_scoped(setup):
    _, _, _, engine, _ = setup
    other = mapping.bind_summary_records(StorageScope('management','tenant-b','other',{SUMMARY_DATASET}),engine)
    try:
        assert other.get(SUMMARY_DATASET,1,context=context()) is None
        with pytest.raises(NotFound):
            SummaryScheduleJournal(other,authorize=lambda *a,**kw:None).record(1,context=context())
    finally:other.close()


def test_completion_failure_rolls_back_summary_time_and_attempt(setup, monkeypatch):
    journal, records, _, _, _ = setup
    enabled(setup); handle = admit(setup)
    before = journal.record(1, context=context())
    original = type(records).patch
    def fail_after_write(self, dataset, key, patch, **kwargs):
        value = original(self, dataset, key, patch, **kwargs)
        if 'knowledge_describe' in patch.set_values:
            raise RuntimeError('controlled transaction failure')
        return value
    monkeypatch.setattr(type(records), 'patch', fail_after_write)
    with pytest.raises(RuntimeError):
        journal.complete(handle, 'must roll back', data_revision='a'*64, model_id=5, context=context())
    assert journal.record(1, context=context()) == before


def test_stale_sample_cannot_admit_after_settings_change(setup):
    enabled(setup)
    before = setup[0].record(1, context=context())
    setup[0].configure('kb-one', '1d', context=context())
    with pytest.raises(Conflict):
        setup[0].admit(before, data_revision='a'*64, knowledge_revision=knowledge_search_revision(before),
                       model_id=5, context=context())


@pytest.mark.parametrize('change', [{'frequency':'bad'}, {'summary':'x'*3001}])
def test_invalid_setting_or_oversized_summary_never_publishes(setup, change):
    from nexent.storage.errors import InvalidInput
    if 'frequency' in change:
        with pytest.raises(InvalidInput): setup[0].configure('kb-one', change['frequency'], context=context())
        assert setup[0].record(1, context=context())['version'] == 0
    else:
        enabled(setup); handle = admit(setup)
        with pytest.raises(InvalidInput):
            setup[0].complete(handle, change['summary'], data_revision='a'*64, model_id=5, context=context())
        assert setup[0].record(1, context=context())['knowledge_describe'] is None


def test_unknown_admission_receipt_is_not_replayed(setup, monkeypatch):
    from nexent.storage.errors import OutcomeUnknown
    from nexent.storage.models import WriteOutcome, WriteReceipt

    enabled(setup)
    calls=[]
    def unknown(*args, **kwargs):
        calls.append(True)
        return WriteReceipt('controlled-unknown',True,outcome=WriteOutcome.UNKNOWN)
    monkeypatch.setattr(type(setup[1]),'patch',unknown)
    with pytest.raises(OutcomeUnknown):admit(setup)
    assert calls==[True]
    assert setup[0].record(1,context=context())['summary_schedule']['attempt'] is None
