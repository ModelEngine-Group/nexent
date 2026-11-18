# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private task archives require explicit quiescence and cannot overwrite evidence."""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.maintenance import knowledge as module
from management.services.knowledge_base import legacy_tasks
from nexent.storage.errors import InvalidInput


@pytest.fixture
def archive(tmp_path, monkeypatch):
    inspector = Mock()
    inspector.scan.return_value = {'tasks': 0, 'snapshot': False}
    monkeypatch.setattr(legacy_tasks, 'LegacyTaskInspector', Mock(return_value=inspector))
    args = SimpleNamespace(knowledge_id=1, tenant_id='tenant', user_id='operator', output=tmp_path/'archive.jsonl',
        legacy_quiesced=True, timeout=2, page_size=1)
    return args, inspector


async def test_archive_records_confirmation_and_current_actor_without_writes(archive, monkeypatch):
    args, inspector = archive
    opened = Mock(side_effect=os.open)
    monkeypatch.setattr(module.os, 'open', opened)
    result = await module.archive_tasks(args)
    lines = [json.loads(line) for line in args.output.read_text().splitlines()]
    assert lines[0]['legacy_quiesced'] is True and lines[0]['actor_id'] == 'operator'
    assert lines[-1]['kind'] == 'legacy_task_archive_inventory_finished'
    assert result['migration_ready'] is False and result['snapshot'] is False
    assert inspector.scan.call_args.args[1].user_id == 'operator'
    assert inspector.scan.call_args.kwargs['archive'] is True
    assert opened.call_args.args[1] & os.O_EXCL and opened.call_args.args[2] == 0o600


async def test_unconfirmed_archive_is_incomplete_and_does_not_scan(archive):
    args, inspector = archive
    args.legacy_quiesced = False
    with pytest.raises(InvalidInput): await module.archive_tasks(args)
    inspector.scan.assert_not_called()
    assert 'inventory_finished' not in args.output.read_text()


async def test_private_archive_is_not_overwritten(archive):
    args, inspector = archive
    args.output.write_text('retained')
    with pytest.raises(FileExistsError): await module.archive_tasks(args)
    inspector.scan.assert_not_called()
    assert args.output.read_text() == 'retained'


def test_cli_requires_explicit_quiescence_before_running(monkeypatch):
    run = Mock()
    monkeypatch.setattr(module.asyncio, 'run', run)
    with pytest.raises(SystemExit) as error:
        module.main(['archive-tasks', '--tenant-id', 'tenant', '--user-id', 'operator', '--knowledge-id', '1', '--output', 'out'])
    assert error.value.code == 2
    run.assert_not_called()
