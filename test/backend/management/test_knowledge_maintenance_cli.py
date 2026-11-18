# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The maintenance CLI streams read evidence and never accepts an execution mode."""

import asyncio
import json
from threading import Event, current_thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_maintenance import SourceFinding, SourceInspectionPage
from management.maintenance import knowledge as module
from nexent.storage.errors import Conflict, DeadlineExceeded, Unavailable


@pytest.fixture
def cli(tmp_path, monkeypatch):
    page = SourceInspectionPage(knowledge_id=1, index_name='kb', tenant_id='tenant', actor_id='operator',
        knowledge_revision='a'*64, files=[SourceFinding(file_id='b'*32)], next_cursor=None)
    inspector = Mock(page=Mock(return_value=page))
    factory = Mock(return_value=inspector)
    monkeypatch.setattr(module, 'KnowledgeSourceInspector', factory)
    args = SimpleNamespace(user_id='operator', tenant_id='tenant', knowledge_id=1, output=tmp_path/'report.jsonl',
        timeout=2, page_size=1)
    return SimpleNamespace(args=args, page=page, inspector=inspector, factory=factory)


async def test_jsonl_pages_use_managed_worker_and_finished_marker(cli):
    s = cli; observed = []
    def page(*args, **kwargs):
        observed.append(current_thread().name)
        kwargs['context'].remaining()
        return s.page.model_copy(update={'next_cursor': 'next' if len(observed) == 1 else None})
    s.inspector.page.side_effect = page
    result = await module.inspect_sources(s.args)
    lines = [json.loads(line) for line in s.args.output.read_text().splitlines()]
    assert [line['kind'] for line in lines] == ['source_inventory_start', 'source_page', 'source_page', 'source_inventory_finished']
    assert result['scan_complete'] and result['files'] == 2 and result['migration_ready'] is False
    assert result['pending_checks'] and all(name != 'MainThread' for name in observed)
    assert s.inspector.page.call_args_list[1].kwargs['cursor'] == 'next'
    assert s.factory.call_args.kwargs['cancellation_scope'].cancelled


async def test_existing_report_is_not_overwritten_and_does_not_query_storage(cli):
    s = cli; s.args.output.write_text('keep')
    with pytest.raises(FileExistsError): await module.inspect_sources(s.args)
    assert s.args.output.read_text() == 'keep'
    s.inspector.page.assert_not_called()


async def test_storage_error_leaves_incomplete_report_without_retry(cli):
    s = cli; s.inspector.page.side_effect = Unavailable()
    with pytest.raises(Unavailable): await module.inspect_sources(s.args)
    assert len(s.args.output.read_text().splitlines()) == 1
    s.inspector.page.assert_called_once()


async def test_resource_revision_change_between_pages_is_not_complete(cli):
    s = cli
    s.inspector.page.side_effect = [s.page.model_copy(update={'next_cursor': 'next'}),
                                   s.page.model_copy(update={'knowledge_revision': 'c'*64})]
    with pytest.raises(Conflict): await module.inspect_sources(s.args)
    assert 'source_inventory_finished' not in s.args.output.read_text()


async def test_cancel_closes_owned_blocking_resource_and_drains_worker(cli):
    s = cli; started, released = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    def blocked(*args, **kwargs):
        scope = s.factory.call_args.kwargs['cancellation_scope']
        token = scope.register_closer(released.set)
        try:
            loop.call_soon_threadsafe(started.set)
            assert released.wait(2)
            kwargs['context'].remaining()
        finally: scope.unregister_closer(token)
    s.inspector.page.side_effect = blocked
    task = asyncio.create_task(module.inspect_sources(s.args))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert released.is_set() and 'source_inventory_finished' not in s.args.output.read_text()
    s.inspector.page.assert_called_once()


async def test_total_deadline_closes_resource_and_keeps_operation_identity(cli):
    s = cli; s.args.timeout = 0.2
    released = Event()
    def blocked(*args, **kwargs):
        scope = s.factory.call_args.kwargs['cancellation_scope']
        token = scope.register_closer(released.set)
        try:
            assert released.wait(2)
            kwargs['context'].remaining()
        finally: scope.unregister_closer(token)
    s.inspector.page.side_effect = blocked
    with pytest.raises(DeadlineExceeded) as caught:
        await module.inspect_sources(s.args)
    assert caught.value.operation_id.startswith('knowledge-source-inspection-')
    assert released.is_set() and 'source_inventory_finished' not in s.args.output.read_text()
    s.inspector.page.assert_called_once()


def argv(cli):
    return ['inspect', '--tenant-id', 'tenant', '--user-id', 'operator', '--knowledge-id', '1', '--output', str(cli.args.output)]


@pytest.mark.parametrize('extra', [['--apply'], ['--page-size', '0'], ['--timeout', '3601'], ['--knowledge-id', '0']])
def test_cli_rejects_mutation_mode_or_unbounded_selection(cli, extra):
    with pytest.raises(SystemExit) as caught: module.main(argv(cli) + extra)
    assert caught.value.code == 2
    cli.inspector.page.assert_not_called()


def test_timeout_logs_once_without_exporting_error_payload(cli, monkeypatch, caplog):
    monkeypatch.setattr(module, 'inspect_sources', AsyncMock(side_effect=DeadlineExceeded()))
    assert module.main(argv(cli)) == 1
    assert len(caplog.records) == 1 and caplog.records[0].levelname == 'WARNING'
    assert 'knowledge_source_inspection_timeout' in caplog.text and 'threshold_seconds=300' in caplog.text


def test_unexpected_error_message_is_redacted(cli, monkeypatch, caplog):
    monkeypatch.setattr(module, 'inspect_sources', AsyncMock(side_effect=RuntimeError('https://secret:password@host/?key=value')))
    assert module.main(argv(cli)) == 1
    assert 'exception_type=RuntimeError' in caplog.text and 'secret' not in caplog.text and 'password' not in caplog.text
