# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Selected read-only KB inventories; no migration execution mode."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.knowledge_maintenance import (
    PENDING_CHECKS,
    RUNTIME_PENDING_CHECKS,
    TASK_PENDING_CHECKS,
    VECTOR_PENDING_CHECKS,
)
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


def _scan_sources(args, scope, context, emit):
    inspector = KnowledgeSourceInspector(cancellation_scope=scope)
    cursor, revision, count, issues = None, None, 0, 0
    while True:
        page = inspector.page(args.knowledge_id, ServicePrincipal(args.user_id, args.tenant_id),
            cursor=cursor, page_size=args.page_size, context=context)
        if revision is not None and page.knowledge_revision != revision: raise Conflict()
        revision = page.knowledge_revision
        context.remaining()
        emit({'kind': 'source_page', **page.model_dump(mode='json')})
        count += len(page.files); issues += sum(bool(item.issues) for item in page.files)
        cursor = page.next_cursor
        if cursor is None: break
    return {'files': count, 'files_with_issues': issues}


def _scan_vectors(args, scope, context, emit):
    from management.services.knowledge_base.legacy_vectors import LegacyVectorInspector

    inspector = LegacyVectorInspector(cancellation_scope=scope)
    return inspector.scan(args.knowledge_id, ServicePrincipal(args.user_id, args.tenant_id),
        lambda page: emit({'kind': 'legacy_vector_page', **page.model_dump(mode='json')}), page_size=args.page_size, context=context)


async def _inspect(args, scanner, kind, pending):
    actor = ServicePrincipal(args.user_id, args.tenant_id)
    scope = RunCancellationScope()
    context = OperationContext('knowledge-' + kind + '-inspection-' + uuid4().hex, monotonic() + args.timeout, cancelled=scope.stop_event)
    manager = ThreadManager(service_name='management-knowledge-inspection', lane_policies={
        'control-io': LanePolicy('control-io', 1, 0, cancel_grace_seconds=5, shutdown_grace_seconds=15),
    })
    manager.start(); set_default_thread_manager(manager)
    try:
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            _emit(stream, {'kind': kind + '_inventory_start', 'operation_id': context.operation_id,
                'knowledge_id': args.knowledge_id, 'tenant_id': actor.tenant_id, 'actor_id': actor.user_id,
                'pending_checks': list(pending), 'migration_ready': False})
            async with asyncio.timeout(context.remaining()):
                emit = lambda value: _emit(stream, value)
                if asyncio.iscoroutinefunction(scanner):
                    result = await scanner(args, scope, context, emit)
                else:
                    result = await run_blocking('knowledge-' + kind + '-inspection', scanner, args, scope, context,
                        emit, lane='control-io', owner='management.knowledge.maintenance')
            result = {'kind': kind + '_inventory_finished', 'operation_id': context.operation_id, 'scan_complete': True,
                **result, 'pending_checks': list(pending), 'migration_ready': False}
            _emit(stream, result)
            return result
    except TimeoutError as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        scope.cancel()
        clear_default_thread_manager(manager)
        if (await manager.shutdown(timeout=15)).stuck_execution_ids:
            raise RuntimeError('Knowledge inspection worker did not exit')


async def inspect_sources(args):
    return await _inspect(args, _scan_sources, 'source', PENDING_CHECKS)


async def inspect_vectors(args):
    return await _inspect(args, _scan_vectors, 'legacy_vector', VECTOR_PENDING_CHECKS)


def _scan_tasks(args, scope, context, emit):
    from management.services.knowledge_base.legacy_tasks import LegacyTaskInspector

    inspector = LegacyTaskInspector(cancellation_scope=scope)
    return inspector.scan(args.knowledge_id, ServicePrincipal(args.user_id, args.tenant_id),
        lambda page: emit({'kind': 'legacy_task_page', **page.model_dump(mode='json')}), page_size=args.page_size, context=context)


async def inspect_tasks(args):
    return await _inspect(args, _scan_tasks, 'legacy_task', TASK_PENDING_CHECKS)


async def _scan_runtime(args, scope, context, emit):
    from management.services.knowledge_base.runtime_inspection import (
        RuntimeKnowledgeInspector,
    )

    return await RuntimeKnowledgeInspector().scan(args.knowledge_id, ServicePrincipal(args.user_id, args.tenant_id),
        lambda page: emit({'kind': 'runtime_page', **page.model_dump(mode='json')}), page_size=args.page_size, context=context)


async def inspect_runtime(args):
    return await _inspect(args, _scan_runtime, 'runtime', RUNTIME_PENDING_CHECKS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    actions = {'inspect': inspect_sources, 'inspect-vectors': inspect_vectors, 'inspect-tasks': inspect_tasks, 'inspect-runtime': inspect_runtime}
    for command in actions:
        description = 'Read-only knowledge inventory'
        inspect = commands.add_parser(command, help=description)
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
        action = actions[args.command]
        result = asyncio.run(action(args))
        print(json.dumps(result))
        return 0
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_source_inspection_timeout operation_id=%s phase=%s threshold_seconds=%s exception_type=%s',
                       getattr(error, 'operation_id', None), args.command,
                       args.timeout, type(error).__name__)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 -- The CLI must redact unexpected driver exception messages.
        logger.error('knowledge_source_inspection_failed exception_type=%s', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
