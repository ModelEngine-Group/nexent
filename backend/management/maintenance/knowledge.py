# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only source inventory for the selected tenant/KB; no migration execution mode."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.knowledge_maintenance import PENDING_CHECKS
from management.services.knowledge_base.source_inspection import (
    KnowledgeSourceInspector,
)
from nexent.core.concurrency import (
    LanePolicy,
    RunCancellationScope,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal

logger = logging.getLogger(__name__)


def _emit(stream, value):
    stream.write(json.dumps(value, ensure_ascii=True) + '\n')
    stream.flush()


async def inspect_sources(args):
    actor = ServicePrincipal(args.user_id, args.tenant_id)
    scope = RunCancellationScope()
    context = OperationContext('knowledge-source-inspection-' + uuid4().hex, monotonic() + args.timeout, cancelled=scope.stop_event)
    inspector = KnowledgeSourceInspector(cancellation_scope=scope)
    manager = ThreadManager(service_name='management-knowledge-inspection', lane_policies={
        'control-io': LanePolicy('control-io', 1, 0, cancel_grace_seconds=5, shutdown_grace_seconds=15),
    })
    manager.start(); set_default_thread_manager(manager)
    try:
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            _emit(stream, {'kind': 'source_inventory_start', 'operation_id': context.operation_id,
                'knowledge_id': args.knowledge_id, 'tenant_id': actor.tenant_id, 'actor_id': actor.user_id,
                'pending_checks': list(PENDING_CHECKS), 'migration_ready': False})
            cursor, revision, count, issues = None, None, 0, 0
            async with asyncio.timeout(context.remaining()):
                while True:
                    page = await run_blocking('knowledge-source-inspection', inspector.page, args.knowledge_id, actor,
                        cursor=cursor, page_size=args.page_size, context=context, lane='control-io', owner='management.knowledge.maintenance')
                    if revision is not None and page.knowledge_revision != revision:
                        raise Conflict()
                    revision = page.knowledge_revision
                    _emit(stream, {'kind': 'source_page', **page.model_dump(mode='json')})
                    count += len(page.files)
                    issues += sum(bool(item.issues) for item in page.files)
                    cursor = page.next_cursor
                    if cursor is None:
                        break
            result = {'kind': 'source_inventory_finished', 'operation_id': context.operation_id, 'scan_complete': True,
                'files': count, 'files_with_issues': issues, 'pending_checks': list(PENDING_CHECKS), 'migration_ready': False}
            _emit(stream, result)
            return result
    except TimeoutError as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        scope.cancel()
        clear_default_thread_manager(manager)
        if (await manager.shutdown(timeout=15)).stuck_execution_ids:
            raise RuntimeError('Source inspection worker did not exit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('inspect', help='Inspect source evidence; no database or object writes')
    inspect.add_argument('--tenant-id', required=True)
    inspect.add_argument('--user-id', required=True, help='Actual operator; current membership and edit DAC are required')
    inspect.add_argument('--knowledge-id', type=int, required=True)
    inspect.add_argument('--output', type=Path, required=True, help='New JSONL report path; existing reports are never overwritten')
    inspect.add_argument('--page-size', type=int, default=100)
    inspect.add_argument('--timeout', type=int, default=300, help='Total deadline in seconds, at most 3600')
    args = parser.parse_args(argv)
    if (not 1 <= args.page_size <= 1000 or not 1 <= args.timeout <= 3600 or args.knowledge_id <= 0
        or any(not value.strip() or len(value) > 100 for value in (args.tenant_id, args.user_id))):
        parser.error('Select one KB, nonempty operator/tenant, page size 1..1000, and timeout 1..3600')
    try:
        result = asyncio.run(inspect_sources(args))
        print(json.dumps(result))
        return 0
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_source_inspection_timeout operation_id=%s phase=source_inventory threshold_seconds=%s exception_type=%s',
                       getattr(error, 'operation_id', None), args.timeout, type(error).__name__)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 -- The CLI must redact unexpected driver exception messages.
        logger.error('knowledge_source_inspection_failed exception_type=%s', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
