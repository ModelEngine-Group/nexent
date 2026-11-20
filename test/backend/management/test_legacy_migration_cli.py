# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit migration files are bounded, complete, actor-bound and never overwritten."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_ingestion import LegacyIngestionSnapshot
from management.maintenance import migration as module
from nexent.storage.errors import DeadlineExceeded, InvalidInput, ScopeDenied

from test.backend.services.test_knowledge_ingestion_contract import intent


@pytest.fixture
def cli(tmp_path):
    value=intent()
    snapshot=LegacyIngestionSnapshot(tenant_id='tenant-a',resource_revision='a'*64,lifecycle_revision=3,legacy_quiesced=True,
        previous={'status':'COMPLETED','stage':'COMPLETE','processing_attempt':0})
    value=value.model_copy(update={'legacy_snapshot':snapshot})
    args=SimpleNamespace(action='plan',tenant_id='tenant-a',user_id='user-a',knowledge_id=1,file_id=value.file_id,
        output=tmp_path/'plan.jsonl',plan=None,legacy_quiesced=True,timeout=2)
    service=Mock(plan=AsyncMock(return_value=value),admit=AsyncMock(return_value={'status':'UPLOADED','stage':'INGEST_ACCEPTED','ingestion_request':value.model_dump(mode='json')}),
        execute=AsyncMock(return_value={'status':'COMPLETED','stage':'COMPLETE','ingestion_request':value.model_dump(mode='json')}),
        inspect=AsyncMock(return_value={'status':'UPLOADED','stage':'INGEST_ACCEPTED','ingestion_request':value.model_dump(mode='json')}),
        restore=AsyncMock(return_value={'status':'COMPLETED','stage':'COMPLETE','ingestion_request':None}))
    return SimpleNamespace(args=args,service=service,value=value)


async def test_complete_plan_can_be_loaded_and_applied_explicitly(cli):
    s=cli
    result=await module.run(s.args,service=s.service)
    assert result['state']=='planned' and not result['migration_complete']
    assert module.load_plan(s.args.output)==s.value
    s.args.plan=s.args.output;s.args.output=s.args.output.with_name('admit.jsonl');s.args.action='admit'
    admitted=await module.run(s.args,service=s.service)
    assert admitted['stage']=='INGEST_ACCEPTED' and not admitted['migration_complete']
    s.service.admit.assert_awaited_once()
    s.service.execute.assert_not_awaited()


async def test_archive_path_is_forwarded_only_to_explicit_plan_and_admission(cli):
    s = cli
    s.args.task_archive = s.args.output.with_name('private-task-archive.jsonl')
    await module.run(s.args, service=s.service)
    assert s.service.plan.call_args.kwargs['task_archive'] == s.args.task_archive
    s.args.plan = s.args.output
    s.args.output = s.args.plan.with_name('admission.jsonl')
    s.args.action = 'admit'
    await module.run(s.args, service=s.service)
    assert s.service.admit.call_args.kwargs['task_archive'] == s.args.task_archive


async def test_explicit_source_binding_choice_is_frozen_in_plan_only(cli):
    s = cli
    s.args.bind_observed_source = True
    await module.run(s.args, service=s.service)
    assert s.service.plan.call_args.kwargs['bind_observed_source'] is True


async def test_execute_and_restore_distinguish_new_completion_from_old_completed_state(cli):
    s=cli;await module.run(s.args,service=s.service)
    s.args.plan=s.args.output
    for action,complete in [('execute',True),('restore',False)]:
        s.args.action=action;s.args.output=s.args.plan.with_name(action+'.jsonl')
        result=await module.run(s.args,service=s.service)
        assert result['migration_complete'] is complete and result['retirement_complete'] is False


async def test_other_actor_and_incomplete_plan_cannot_trigger_write(cli):
    s=cli;await module.run(s.args,service=s.service)
    s.args.plan=s.args.output;s.args.output=s.args.plan.with_name('wrong.jsonl');s.args.action='admit';s.args.user_id='owner'
    with pytest.raises(ScopeDenied):await module.run(s.args,service=s.service)
    s.service.admit.assert_not_awaited()
    lines=s.args.plan.read_text().splitlines();s.args.plan.write_text('\n'.join(lines[:-1]))
    with pytest.raises(InvalidInput):module.load_plan(s.args.plan)


async def test_existing_output_does_not_prepare_or_submit_anything(cli):
    s=cli;s.args.output.write_text('keep')
    with pytest.raises(FileExistsError):await module.run(s.args,service=s.service)
    assert s.args.output.read_text()=='keep'
    s.service.plan.assert_not_awaited()


async def test_default_service_receives_the_owned_cancellation_scope(cli,monkeypatch):
    factory=Mock(return_value=cli.service)
    monkeypatch.setattr(module,'LegacyMigrationService',factory)
    await module.run(cli.args)
    scope=factory.call_args.kwargs['cancellation_scope']
    assert scope.cancelled


async def test_archive_report_is_exclusive_and_owner_only(cli,mocker):
    original=module.os.open
    opened=mocker.patch.object(module.os,'open',side_effect=original)
    await module.run(cli.args,service=cli.service)
    call=next(call for call in opened.call_args_list if call.args[0]==cli.args.output)
    assert call.args[1] & module.os.O_EXCL and call.args[2]==0o600


async def test_inspection_reports_a_matching_receipt_without_calling_write_actions(cli):
    s=cli;await module.run(s.args,service=s.service)
    s.args.plan=s.args.output;s.args.output=s.args.plan.with_name('observed.jsonl');s.args.action='inspect'
    s.service.inspect=AsyncMock(return_value={'status':'UPLOADED','stage':'INGEST_ACCEPTED','version':4,
        'ingestion_request':s.value.model_dump(mode='json')})
    result=await module.run(s.args,service=s.service)
    assert result['state']=='observed' and result['intent_matches_plan'] is True
    s.service.admit.assert_not_awaited();s.service.execute.assert_not_awaited();s.service.restore.assert_not_awaited()


def test_read_only_inspection_does_not_require_new_quiescence_confirmation(cli,monkeypatch):
    action=AsyncMock(return_value={'state':'observed'})
    monkeypatch.setattr(module,'run',action)
    args=['inspect','--tenant-id','tenant-a','--user-id','user-a','--knowledge-id','1','--file-id',cli.value.file_id,
        '--plan',str(cli.args.output),'--output',str(cli.args.output.with_name('receipt.jsonl'))]
    assert module.main(args)==0 and action.await_count==1


async def test_total_deadline_cancels_without_finished_marker_or_retry(cli):
    s=cli;s.args.timeout=0.02;closed=[]
    async def blocked(*args,**kwargs):
        try:await asyncio.Event().wait()
        finally:closed.append(True)
    s.service.plan.side_effect=blocked
    with pytest.raises(DeadlineExceeded):await module.run(s.args,service=s.service)
    assert closed==[True] and s.service.plan.await_count==1
    assert 'migration_finished' not in s.args.output.read_text()


@pytest.mark.parametrize('extra',[[],['--legacy-quiesced','--file-id','not-canonical'],['--legacy-quiesced','--timeout','0']])
def test_cli_requires_operator_quiescence_and_bounded_input(cli,extra):
    s=cli
    args=['plan','--tenant-id','tenant-a','--user-id','user-a','--knowledge-id','1','--file-id',s.value.file_id,'--output',str(s.args.output)]
    with pytest.raises(SystemExit) as error:module.main(args+extra)
    assert error.value.code==2 and not s.args.output.exists()


def test_historical_file_id_option_applies_only_to_planning(cli, monkeypatch):
    run = AsyncMock(return_value={'state': 'planned'})
    monkeypatch.setattr(module, 'run', run)
    tail = ['--tenant-id', 'tenant-a', '--user-id', 'user-a', '--knowledge-id', '1',
            '--file-id', 'old-file', '--output', str(cli.args.output), '--legacy-quiesced']
    with pytest.raises(SystemExit):
        module.main(['plan', *tail])
    assert module.main(['plan', *tail, '--map-legacy-file-id']) == 0
    assert run.call_args.args[0].map_legacy_file_id is True
    with pytest.raises(SystemExit):
        module.main(['admit', *tail, '--map-legacy-file-id', '--plan', str(cli.args.output)])
