# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Automatic summaries keep current DAC, durable admission and authorized AgentOS inputs."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeSampleResult
from contracts.knowledge_summary import SUMMARY_DATASET, SUMMARY_MODEL_DATASET
from management.services.knowledge_base.summary_coordinator import (
    SummaryCoordinator,
    is_due,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import StorageScope

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.rdb import cleanse_resources, knowledge_summary
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_summary_schedule import (
    isolated_connections,  # noqa: F401
)
from test.backend.services.test_knowledge_summary_schedule import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_summary_schedule import (
    setup as setup,  # noqa: PLC0414
)


@pytest.fixture
async def manager():
    manager = ThreadManager(service_name='summary-coordinator-test', lane_policies={
        'control-io': LanePolicy('control-io', 1, 4, queue_timeout_seconds=1),
    })
    manager.start(); set_default_thread_manager(manager)
    try:
        yield manager
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids


async def record(s):
    return await run_blocking('test-summary-record', s.journal.record, 1, context=context(), lane='control-io')


async def configure(s, frequency):
    return await run_blocking('test-summary-configure', s.journal.configure, 'kb-one', frequency, context=context(), lane='control-io')


@pytest.fixture
def coordinator(setup, monkeypatch, manager):
    journal, _, update, engine, _ = setup
    row = journal.configure('kb-one', '3h', context=context())
    config = sa.Table('summary_model_fixture', sa.MetaData(), sa.Column('tenant_config_id', sa.Integer, primary_key=True),
        sa.Column('tenant_id', sa.String), sa.Column('config_key', sa.String), sa.Column('config_value', sa.String),
        sa.Column('delete_flag', sa.String))
    config.create(engine)
    monkeypatch.setattr(knowledge_summary, 'TenantConfig', SimpleNamespace(__table__=config))
    with engine.begin() as connection:
        connection.execute(config.insert(), {'tenant_config_id': 1, 'tenant_id': 'tenant-a', 'config_key': 'LLM_ID',
            'config_value': '5', 'delete_flag': 'N'})
    closed, identities = [], []

    @contextmanager
    def ports(tenant_id, user_id, *, context, models=False):
        identities.append((tenant_id, user_id))
        names = {SUMMARY_DATASET, SUMMARY_MODEL_DATASET} if models else {SUMMARY_DATASET}
        records = knowledge_summary.bind_summary_records(StorageScope('management', tenant_id, user_id, names), engine)
        resources = cleanse_resources.bind_cleanse_resources(StorageScope('management', tenant_id, user_id,
            set(cleanse_resources.TABLES)), engine)
        try:
            yield records, resources
        finally:
            records.close(); resources.close(); closed.append(True)

    sample = KnowledgeSampleResult(knowledge_id=1, knowledge_revision=knowledge_search_revision(row), data_revision='a'*64,
        embedding_model={'model_id': 2, 'revision': 'v1'}, documents=[{'file_ref': {
            'knowledge_id': 1, 'file_id': 'b'*32, 'file_version': 0}, 'filename': 'one.txt',
            'chunks': [{'chunk_index': 0, 'content': 'one', 'embedding': [1., 0.]}]}])
    service = SimpleNamespace(sample=AsyncMock(return_value=sample), summarize_sample=AsyncMock(return_value='<p>summary</p>'))
    return SimpleNamespace(coordinator=SummaryCoordinator(summary=service, ports=ports), journal=journal,
        update=update, engine=engine, config=config, closed=closed, identities=identities, ports=ports,
        service=service, sample=sample, candidate={'knowledge_id': 1, 'index_name': 'kb-one', 'user_id': 'user-a', 'tenant_id': 'tenant-a'})


async def test_admits_before_models_then_atomically_completes_as_actual_issuer(coordinator):
    s = coordinator
    async def summarize(sample, **kwargs):
        row = await record(s)
        assert row['summary_schedule']['attempt']['status'] == 'admitted'
        assert row['knowledge_describe'] is None
        assert sample is s.sample and kwargs == {'user_id': 'user-a', 'tenant_id': 'tenant-a', 'language': 'zh', 'model_id': 5}
        return '<p>summary</p>'
    s.service.summarize_sample.side_effect = summarize
    assert await s.coordinator.advance(s.candidate) is True
    row = await record(s)
    assert row['summary_schedule']['attempt']['status'] == 'completed'
    assert row['knowledge_describe'] == '<p>summary</p>' and row['last_summary_time']
    assert row['updated_by'] == 'user-a'
    assert s.service.sample.await_args_list[0].kwargs['batch_size'] == 200
    assert s.service.sample.await_args_list[1].kwargs['batch_size'] == 5
    assert all(value == ('tenant-a', 'user-a') for value in s.identities) and len(s.identities) == len(s.closed)


async def test_failed_version_is_not_invoked_again_even_by_fresh_coordinator(coordinator):
    s = coordinator
    s.service.summarize_sample.side_effect = ValueError('controlled model failure')
    with pytest.raises(ValueError): await s.coordinator.advance(s.candidate)
    row = await record(s)
    assert row['summary_schedule']['attempt']['status'] == 'failed' and row['knowledge_describe'] is None
    s.service.summarize_sample.reset_mock()
    assert await SummaryCoordinator(summary=s.service, ports=s.ports).advance(s.candidate) is False
    s.service.summarize_sample.assert_not_awaited()


@pytest.mark.parametrize('change', ['actor', 'tenant', 'index', 'revoked', 'private', 'deleting'])
async def test_discovery_identity_never_bypasses_current_authorization(coordinator, change):
    s = coordinator
    if change in {'actor', 'tenant', 'index'}:
        s.candidate[{'actor': 'user_id', 'tenant': 'tenant_id', 'index': 'index_name'}[change]] = 'other'
    elif change == 'revoked': s.update('cleanse_memberships', delete_flag='Y')
    elif change == 'private': s.update('cleanse_knowledge', created_by='other', ingroup_permission='PRIVATE')
    else: s.update('cleanse_knowledge', deletion_request={'pending': True})
    with pytest.raises((ScopeDenied, Conflict, NotFound)):
        await s.coordinator.advance(s.candidate)
    s.service.sample.assert_not_awaited(); s.service.summarize_sample.assert_not_awaited()


@pytest.mark.parametrize('change', ['model', 'data', 'profile', 'config', 'revoked'])
async def test_late_changes_never_publish_summary(coordinator, change):
    s = coordinator
    async def summarize(*args, **kwargs):
        if change == 'model':
            with s.engine.begin() as connection: connection.execute(s.config.update().values(config_value='6'))
        elif change == 'data':
            s.service.sample.return_value = s.sample.model_copy(update={'data_revision': 'd'*64})
        elif change == 'profile':
            changed = s.sample.model_dump()
            changed['embedding_model']['revision'] = 'v2'
            s.service.sample.return_value = KnowledgeSampleResult.model_validate(changed)
        elif change == 'config': await configure(s, None)
        else: s.update('cleanse_memberships', delete_flag='Y')
        return 'must not publish'
    s.service.summarize_sample.side_effect = summarize
    with pytest.raises((Conflict, ScopeDenied)): await s.coordinator.advance(s.candidate)
    assert (await record(s))['knowledge_describe'] is None


@pytest.mark.parametrize('phase', ['admit', 'complete'])
async def test_unknown_write_is_never_followed_by_failure_or_replay(coordinator, monkeypatch, phase):
    s = coordinator
    from management.services.knowledge_base.summary_schedule import (
        SummaryScheduleJournal,
    )
    failure = []
    def unknown(*args, **kwargs): raise OutcomeUnknown()
    monkeypatch.setattr(SummaryScheduleJournal, phase, unknown)
    monkeypatch.setattr(SummaryScheduleJournal, 'fail', lambda *a, **kw: failure.append(True))
    with pytest.raises(OutcomeUnknown): await s.coordinator.advance(s.candidate)
    assert failure == []
    assert s.service.summarize_sample.await_count == (phase == 'complete')


async def test_new_visible_data_can_admit_after_failed_current_version(coordinator):
    s = coordinator
    s.service.summarize_sample.side_effect = ValueError('controlled failure')
    with pytest.raises(ValueError): await s.coordinator.advance(s.candidate)
    s.service.summarize_sample.side_effect = None
    s.service.sample.return_value = s.sample.model_copy(update={'data_revision': 'd'*64})
    assert await s.coordinator.advance(s.candidate)
    assert s.service.summarize_sample.await_count == 2
    assert (await record(s))['summary_schedule']['attempt']['data_revision'] == 'd'*64


@pytest.mark.parametrize('phase', ['admit', 'complete'])
@pytest.mark.parametrize('error', [OutcomeUnknown, DeadlineExceeded])
async def test_write_then_lost_reply_keeps_durable_state_without_followup_write(coordinator, monkeypatch, phase, error):
    from management.services.knowledge_base.summary_schedule import (
        SummaryScheduleJournal,
    )

    s = coordinator
    original = getattr(SummaryScheduleJournal, phase)
    def lost_reply(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise error()
    monkeypatch.setattr(SummaryScheduleJournal, phase, lost_reply)
    with pytest.raises(error): await s.coordinator.advance(s.candidate)
    row = await record(s)
    assert row['summary_schedule']['attempt']['status'] == ('admitted' if phase == 'admit' else 'completed')
    assert row['knowledge_describe'] == (None if phase == 'admit' else '<p>summary</p>')
    assert s.service.summarize_sample.await_count == (phase == 'complete')


@pytest.mark.parametrize('change', ['frequency', 'model'])
async def test_configuration_change_during_sample_never_admits_or_invokes(coordinator, change):
    s = coordinator
    async def sample(*args, **kwargs):
        if change == 'frequency':
            await configure(s, '1d')
        else:
            with s.engine.begin() as connection: connection.execute(s.config.update().values(config_value='6'))
        return s.sample
    s.service.sample.side_effect = sample
    with pytest.raises(Conflict): await s.coordinator.advance(s.candidate)
    s.service.summarize_sample.assert_not_awaited()
    assert (await record(s))['summary_schedule']['attempt'] is None


async def test_ambiguous_default_model_does_not_select_or_invoke(coordinator):
    s = coordinator
    with s.engine.begin() as connection:
        connection.execute(s.config.insert(), {'tenant_config_id': 2, 'tenant_id': 'tenant-a', 'config_key': 'LLM_ID',
            'config_value': '6', 'delete_flag': 'N'})
    with pytest.raises(Conflict): await s.coordinator.advance(s.candidate)
    s.service.sample.assert_not_awaited(); s.service.summarize_sample.assert_not_awaited()


@pytest.mark.parametrize('value', [None, 'bad', '-1', '0'])
async def test_missing_default_binding_preserves_existing_placeholder_path(coordinator, value):
    s = coordinator
    with s.engine.begin() as connection: connection.execute(s.config.update().values(config_value=value))
    assert await s.coordinator.advance(s.candidate)
    assert s.service.summarize_sample.await_args.kwargs['model_id'] is None


async def test_cancel_keeps_admitted_attempt_without_late_publication(coordinator):
    s = coordinator
    async def cancelled(*args, **kwargs): raise asyncio.CancelledError()
    s.service.summarize_sample.side_effect = cancelled
    with pytest.raises(asyncio.CancelledError): await s.coordinator.advance(s.candidate)
    row = await record(s)
    assert row['summary_schedule']['attempt']['status'] == 'admitted' and row['knowledge_describe'] is None


@pytest.mark.parametrize('kind', ['missing-issuer', 'disabled', 'not-due'])
async def test_unconfigured_or_not_due_skips_without_network(coordinator, kind):
    s = coordinator
    if kind == 'missing-issuer': s.update('cleanse_knowledge', summary_schedule=None)
    elif kind == 'disabled': await configure(s, None)
    else: s.update('cleanse_knowledge', last_summary_time=datetime.now(UTC).replace(tzinfo=None))
    assert await s.coordinator.advance(s.candidate) is False
    s.service.sample.assert_not_awaited(); s.service.summarize_sample.assert_not_awaited()


@pytest.mark.parametrize('frequency', ['1h', '3h', '6h', '1d', '1w'])
def test_due_keeps_original_interval_and_document_change_rules(frequency):
    from contracts.constants.constants import FREQUENCY_MAP
    now = datetime.now(UTC)
    previous = now - FREQUENCY_MAP[frequency]
    assert is_due(None, frequency, None, now=now)
    assert not is_due(now.isoformat(), frequency, None, now=now)
    assert is_due(previous.isoformat(), frequency, None, now=now)
    assert not is_due(previous.isoformat(), frequency, previous.isoformat(), now=now)
    assert is_due(previous.isoformat(), frequency, now.isoformat(), now=now)
    assert not is_due(None, None, None, now=now)
