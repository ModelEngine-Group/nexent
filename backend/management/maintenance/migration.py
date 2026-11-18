# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit legacy source migration with read-only receipt inspection."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.knowledge_ingestion import KnowledgeIngestionIntent
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


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


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
                if args.action == 'plan':
                    plan = await service.plan(args.knowledge_id,args.file_id,actor,legacy_quiesced=args.legacy_quiesced,context=context)
                    _emit(stream, {'kind':'migration_plan','plan_hash':plan_hash(plan),'intent':plan.model_dump(mode='json')})
                    state, row = 'planned', None
                else:
                    plan = load_plan(args.plan)
                    if (plan.user_id != actor.user_id or plan.legacy_snapshot.tenant_id != actor.tenant_id
                        or plan.knowledge_id != args.knowledge_id or plan.file_id != args.file_id): raise ScopeDenied()
                    row = await getattr(service,args.action)(plan,actor,context=context)
                    state = 'restored' if args.action == 'restore' else 'observed'
            context.remaining()
            matches = False
            if row and row.get('ingestion_request') is not None:
                try: matches = KnowledgeIngestionIntent.model_validate(row['ingestion_request']) == plan
                except ValidationError: matches = None
            result = {'kind':'migration_finished','state':state,'plan_hash':plan_hash(plan),'file_id':plan.file_id,
                'stage':row['stage'] if row else None,'status':row['status'] if row else None,
                'lifecycle_revision':row.get('version') if row else None,'intent_matches_plan':matches,
                'migration_complete':args.action in {'inspect','admit','execute'} and matches is True and row['stage']=='COMPLETE' and row['status']=='COMPLETED',
                'retirement_complete':False}
            _emit(stream,result);return result
    except TimeoutError as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        scope.cancel();clear_default_thread_manager(manager)
        if (await manager.shutdown(timeout=15)).stuck_execution_ids: raise RuntimeError('Migration worker did not exit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','inspect','admit','execute','restore'])
    parser.add_argument('--tenant-id',required=True);parser.add_argument('--user-id',required=True)
    parser.add_argument('--knowledge-id',required=True,type=int);parser.add_argument('--file-id',required=True)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--plan',type=Path)
    parser.add_argument('--legacy-quiesced',action='store_true',help='Operator confirms old admission and workers are stopped and drained')
    parser.add_argument('--timeout',type=int,default=300)
    args = parser.parse_args(argv)
    if (args.action != 'inspect' and not args.legacy_quiesced or not 1 <= args.timeout <= 3600 or args.knowledge_id <= 0
        or any(not value.strip() or len(value)>100 for value in (args.user_id,args.tenant_id))
        or len(args.file_id)!=32 or any(c not in '0123456789abcdef' for c in args.file_id)
        or args.action!='plan' and args.plan is None or args.action=='plan' and args.plan is not None):
        parser.error('Select a canonical file, actual actor/tenant, deadline 1..3600 and confirmed legacy quiescence; non-plan actions require --plan')
    try:
        print(json.dumps(asyncio.run(run(args))));return 0
    except (TimeoutError,DeadlineExceeded) as error:
        logger.warning('legacy_migration_timeout operation_id=%s action=%s threshold_seconds=%s exception_type=%s',
            getattr(error,'operation_id',None),args.action,args.timeout,type(error).__name__);return 1
    except KeyboardInterrupt:return 130
    except Exception as error:  # noqa: BLE001 -- Never log provider payloads or archived legacy errors.
        logger.error('legacy_migration_failed action=%s exception_type=%s',args.action,type(error).__name__);return 1


if __name__ == '__main__':raise SystemExit(main())
