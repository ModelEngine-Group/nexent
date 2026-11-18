# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""LT-03/05: current DAC, lifecycle references and redacted task evidence."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_maintenance import LEGACY_TASKS
from management.services.knowledge_base.legacy_tasks import LegacyTaskInspector
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import Page, StorageScope

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_source_inspection import (
    inspection as source_fixture,  # noqa: F401
)


@pytest.fixture
def inspection(source_fixture):  # noqa: F811 -- Imported pytest fixture is injected by name.
    source_fixture.update(process_task_id='old-task')
    actor = source_fixture.actor
    records = Mock(scope=StorageScope('management', actor.tenant_id, actor.user_id, {LEGACY_TASKS}))
    row = {'task_id': 'old-task', 'status': 'STARTED', 'revision': 'a'*64, 'result_present': True,
        'metadata_valid': True, 'index_matches': True, 'tenant_matches': None, 'file_id': 'b'*32,
        'origin': 'pg_reference', 'auxiliary_present': ['chunks']}
    records.get.return_value = row
    records.query.return_value = Page((row, {**row, 'task_id': 'redis-only', 'origin': 'index_metadata'}))
    closed, frames, expected_known = [], [], {'old-task'}
    @contextmanager
    def tasks(*args, **kwargs):
        assert kwargs['known_tasks'] == expected_known
        try: yield records
        finally: closed.append(True)
    return SimpleNamespace(service=LegacyTaskInspector(ports=source_fixture.service.ports, tasks=tasks),
        source=source_fixture, records=records, row=row, closed=closed, frames=frames, expected_known=expected_known)


def scan(s):
    return s.service.scan(1, s.source.actor, s.frames.append, page_size=2, context=context())


def test_modern_ingestion_references_are_not_read_from_legacy_redis(inspection):
    from contracts.knowledge_cleanse import cleanse_job_id

    from test.backend.services.test_knowledge_ingestion_contract import intent
    s=inspection;value=intent()
    s.source.update(ingestion_request=value.model_dump(mode='json'),
        process_task_id=cleanse_job_id(value.cleanse_request(),'tenant-a','user-a'))
    s.expected_known.clear();s.records.query.return_value=Page(())
    result=scan(s)
    assert result['tasks']==0 and result['managed_files_not_scanned']==1
    s.records.get.assert_not_called()


def test_unknown_ingestion_intent_is_reported_unreconciled_without_guessing_task_origin(inspection):
    s=inspection
    s.source.update(ingestion_request={'unknown':'legacy-or-corrupt'})
    s.expected_known.clear();s.records.query.return_value=Page(())
    result=scan(s)
    assert result['unreconciled_ingestion_intents']==1 and result['managed_files_not_scanned']==0
    s.records.get.assert_not_called()


def test_known_and_redis_only_tasks_are_deduplicated_and_redacted(inspection):
    s = inspection; result = scan(s)
    assert result['tasks'] == 2 and result['tasks_with_issues'] == 2
    assert result['redis_only_tasks'] == 1 and result['snapshot'] is False
    rows = [row for frame in s.frames for row in frame.tasks]
    assert all(len(row.task_id_hash) == 64 for row in rows)
    assert 'old-task' not in ''.join(frame.model_dump_json() for frame in s.frames)
    assert 'LEGACY_TASK_NOT_TERMINAL' in rows[0].issues
    assert 'REDIS_ONLY_TASK' in rows[1].issues
    assert s.closed == [True]


@pytest.mark.parametrize('changes,code', [({'result_present': False, 'status': 'UNKNOWN'}, 'LEGACY_RESULT_MISSING'),
    ({'metadata_valid': False}, 'LEGACY_METADATA_INVALID'), ({'index_matches': False}, 'LEGACY_TASK_INDEX_CONFLICT'),
    ({'tenant_matches': False}, 'LEGACY_TASK_TENANT_CONFLICT'), ({'file_id': 'c'*32}, 'LEGACY_TASK_FILE_CONFLICT')])
def test_conflicting_and_missing_states_remain_findings(inspection, changes, code):
    s = inspection; s.row.update(changes)
    scan(s)
    assert code in s.frames[0].tasks[0].issues


def test_permission_revocation_before_scan_prevents_task_reads(inspection):
    s = inspection; s.source.update_resource('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied): scan(s)
    s.records.get.assert_not_called(); s.records.query.assert_not_called()


def test_file_task_reference_change_discards_inflight_page(inspection):
    s = inspection
    def changed(*args, **kwargs):
        s.source.update(process_task_id='changed-task')
        return s.row
    s.records.get.side_effect = changed
    with pytest.raises(Conflict): scan(s)
    assert not s.frames and s.closed == [True]


def test_task_backend_failure_is_not_an_empty_finished_scan(inspection):
    s = inspection; s.records.get.side_effect = Unavailable()
    with pytest.raises(Unavailable): scan(s)
    assert not s.frames and s.records.get.call_count == 1
