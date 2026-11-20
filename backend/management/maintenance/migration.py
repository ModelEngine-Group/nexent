# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit legacy source migration with read-only receipt inspection."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.knowledge_ingestion import (
    KnowledgeIngestionIntent,
    is_canonical_file_id,
    is_historical_file_id,
)
from contracts.knowledge_ingestion import (
    legacy_ingestion_plan_hash as plan_hash,
)
from management.services.knowledge_base.legacy_migration import LegacyMigrationService
from nexent.core.concurrency import (
    LanePolicy,
    RunCancellationScope,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext
from pydantic import ValidationError

from infrastructure.agentos_identity import ServicePrincipal

logger = logging.getLogger(__name__)


def _emit(stream, record):
    stream.write(json.dumps(record, ensure_ascii=True)+'\n');stream.flush()


def load_plan(path):
    if not path.is_file() or path.stat().st_size > 65536: raise InvalidInput()
    lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if len(lines) != 3 or any(not isinstance(line,dict) for line in lines): raise InvalidInput()
    if ([line.get('kind') for line in lines] != ['migration_started', 'migration_plan', 'migration_finished']
        or lines[0].get('action') != 'plan' or lines[2].get('state') != 'planned'): raise InvalidInput()
    plan = KnowledgeIngestionIntent.model_validate(lines[1]['intent'])
    if plan.legacy_snapshot is None or lines[1].get('plan_hash') != plan_hash(plan) or lines[2].get('plan_hash') != plan_hash(plan): raise InvalidInput()
    return plan


async def run(args, *, service=None):
    actor = ServicePrincipal(args.user_id, args.tenant_id)
    scope = RunCancellationScope()
    context = OperationContext('legacy-migration-'+uuid4().hex, monotonic()+args.timeout, cancelled=scope.stop_event)
    manager = ThreadManager(service_name='management-legacy-migration', lane_policies={'control-io': LanePolicy(
        'control-io', 2, 0, cancel_grace_seconds=5, shutdown_grace_seconds=15)})
    manager.start();set_default_thread_manager(manager)
    try:
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8', newline='\n') as stream:
            _emit(stream, {'kind':'migration_started','action':args.action,'operation_id':context.operation_id,
                'actor_id':actor.user_id,'tenant_id':actor.tenant_id,'knowledge_id':args.knowledge_id,'file_id':args.file_id})
            service = service or LegacyMigrationService(cancellation_scope=scope)
            async with asyncio.timeout(context.remaining()):
                archive = {'task_archive': args.task_archive} if getattr(args, 'task_archive', None) is not None else {}
                if args.action == 'plan':
                    if getattr(args, 'bind_observed_source', False): archive['bind_observed_source'] = True
                    if getattr(args, 'map_legacy_file_id', False): archive['map_legacy_file_id'] = True
                    plan = await service.plan(args.knowledge_id,args.file_id,actor,legacy_quiesced=args.legacy_quiesced,context=context,**archive)
                    _emit(stream, {'kind':'migration_plan','plan_hash':plan_hash(plan),'intent':plan.model_dump(mode='json')})
                    state, row = 'planned', None
                else:
                    plan = load_plan(args.plan)
                    identity = plan.legacy_snapshot.previous_file_id if args.action in {'reserve-file-id', 'activate-file-id', 'restore-file-id'} else plan.file_id
                    if (plan.user_id != actor.user_id or plan.legacy_snapshot.tenant_id != actor.tenant_id
                        or plan.knowledge_id != args.knowledge_id or identity != args.file_id): raise ScopeDenied()
                    if args.action == 'reserve-file-id':
                        row = await service.reserve_file_id(plan, actor, context=context, **archive)
                        state = 'identity_reserved'
                    elif args.action == 'activate-file-id':
                        row = await service.activate_file_id(plan, actor, context=context, **archive)
                        state = 'identity_activated'
                    elif args.action == 'restore-file-id':
                        row = await service.restore_file_id(plan, actor, context=context)
                        state = 'identity_restored'
                    elif args.action == 'verify-publication':
                        row = await service.verify_publication(plan, actor, context=context)
                        state = 'publication_verified'
                    else:
                        row = await getattr(service, args.action)(plan, actor, context=context, **archive)
                        state = 'restored' if args.action == 'restore' else 'observed'
            context.remaining()
            matches = False
            if row and row.get('ingestion_request') is not None:
                try: matches = KnowledgeIngestionIntent.model_validate(row['ingestion_request']) == plan
                except ValidationError: matches = None
            result = {'kind':'migration_finished','state':state,'plan_hash':plan_hash(plan),'file_id':plan.file_id,
                'stage':row.get('stage') if row else None,'status':row.get('status') if row else None,
                'lifecycle_revision':row.get('version', row.get('lifecycle_revision')) if row else None,'intent_matches_plan':matches,
                'migration_complete':args.action in {'inspect','admit','execute','verify-publication'} and matches is True and row['stage']=='COMPLETE' and row['status']=='COMPLETED',
                'retirement_complete':False}
            if state == 'publication_verified':
                result['publication_verified'] = True
            if state in {'identity_reserved', 'identity_activated', 'identity_restored'}:
                result['original_file_id'] = plan.legacy_snapshot.previous_file_id
            if state == 'identity_restored':
                result['file_id'] = row['file_id']
            _emit(stream,result);return result
    except TimeoutError as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        scope.cancel();clear_default_thread_manager(manager)
        if (await manager.shutdown(timeout=15)).stuck_execution_ids: raise RuntimeError('Migration worker did not exit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','reserve-file-id','activate-file-id','restore-file-id','inspect',
                                          'verify-publication','admit','execute','restore'])
    parser.add_argument('--tenant-id',required=True);parser.add_argument('--user-id',required=True)
    parser.add_argument('--knowledge-id',required=True,type=int);parser.add_argument('--file-id',required=True)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--plan',type=Path)
    parser.add_argument('--task-archive',type=Path,help='Complete private archive-tasks report for original PG task references')
    parser.add_argument('--bind-observed-source',action='store_true',help='Explicitly pin a proven historical source or same-bucket S3 alias in the plan')
    parser.add_argument('--map-legacy-file-id', action='store_true',
                        help='Plan a standard ID for a historical file without modifying the ledger')
    parser.add_argument('--legacy-quiesced',action='store_true',help='Operator confirms old admission and workers are stopped and drained')
    parser.add_argument('--timeout',type=int,default=300)
    args = parser.parse_args(argv)
    historical_id = args.map_legacy_file_id or args.action in {'reserve-file-id', 'activate-file-id', 'restore-file-id'}
    if (args.action not in {'inspect', 'verify-publication'} and not args.legacy_quiesced
        or not 1 <= args.timeout <= 3600 or args.knowledge_id <= 0
        or any(not value.strip() or len(value)>100 for value in (args.user_id,args.tenant_id))
        or not is_historical_file_id(args.file_id) or historical_id == is_canonical_file_id(args.file_id)
        or args.map_legacy_file_id and args.action != 'plan'
        or args.action!='plan' and args.plan is None or args.action=='plan' and args.plan is not None
        or args.task_archive is not None and args.action in {'inspect','verify-publication','restore','restore-file-id'}
        or args.bind_observed_source and args.action != 'plan'):
        parser.error('Select a file, actor, tenant and deadline. Use the original ID for planning, reserving, activating or restoring a mapping.')
    try:
        print(json.dumps(asyncio.run(run(args))));return 0
    except (TimeoutError,DeadlineExceeded) as error:
        logger.warning('legacy_migration_timeout operation_id=%s action=%s threshold_seconds=%s exception_type=%s',
            getattr(error,'operation_id',None),args.action,args.timeout,type(error).__name__);return 1
    except KeyboardInterrupt:return 130
    except Exception as error:  # noqa: BLE001 -- Never log provider payloads or archived legacy errors.
        logger.error('legacy_migration_failed action=%s exception_type=%s',args.action,type(error).__name__);return 1


if __name__ == '__main__':raise SystemExit(main())
