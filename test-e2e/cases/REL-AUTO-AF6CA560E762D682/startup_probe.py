# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run an owned Config process with controlled persistence and real threads."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager, contextmanager
import json
import os
from pathlib import Path
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fault', choices=('recovery', 'upload', 'configuration'), required=True)
    parser.add_argument('--healthy', action='store_true')
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    for source in (root, root / 'backend', root / 'sdk'):
        sys.path.insert(0, str(source))

    import uvicorn
    import apps.config_app as config_app
    import management.recovery as recovery
    import management.services.evaluation.maintenance as maintenance
    import management.services.memory.dreaming.scheduler as memory
    from nexent.core.concurrency.context import get_default_thread_manager

    def emit(event, **fields):
        record = {'event': event, 'pid': os.getpid(), 'time': time.time(), **fields}
        with args.events.open('a', encoding='utf-8') as output:
            output.write(json.dumps(record) + '\n')

    def recover():
        emit('recover_config_tasks')
        if not args.healthy and args.fault == 'recovery':
            raise RuntimeError('controlled recovery failure')
        return {}

    async def upload_cleanup(service_name):
        assert service_name == config_app.CONFIG_SERVICE_NAME
        emit('upload_cleanup')
        if not args.healthy and args.fault == 'upload':
            raise RuntimeError('controlled upload failure')

    async def dreaming_start():
        emit('dreaming_start')

    async def dreaming_stop():
        emit('dreaming_stop')

    recovery.recover_config_tasks = recover
    recovery.schedule_interrupted_upload_cleanup = upload_cleanup
    recovery.schedule_workbench_main_backfill = lambda: None
    config_app.ENABLE_AGENT_WORKBENCH = False
    config_app.ENABLE_AIDP_KNOWLEDGE = not args.healthy and args.fault == 'configuration'
    config_app.AIDP_SERVER_URL = ''
    config_app.AIDP_API_KEY = ''
    memory.dreaming_scheduler.start = dreaming_start
    memory.dreaming_scheduler.stop = dreaming_stop

    # Retain the real long-lived maintenance loop without any database access,
    # even if a slow test exceeds one maintenance interval.
    maintenance.list_dispatchable_pending_runs = lambda: []

    class EmptyTenantSession:
        def query(self, *_args):
            return self

        def distinct(self):
            return self

        def all(self):
            return []

    @contextmanager
    def controlled_session():
        yield EmptyTenantSession()

    maintenance.get_db_session = controlled_session
    original_lifespan = config_app.app.router.lifespan_context

    @asynccontextmanager
    async def observed_lifespan(app):
        try:
            async with original_lifespan(app):
                emit('startup_completed')
                yield
        except BaseException as error:
            emit('startup_exception', error_type=type(error).__name__, message=str(error))
            raise
        finally:
            emit('lifespan_returned', manager_state=config_app.config_thread_manager.state.value,
                 default_is_owned=get_default_thread_manager() is config_app.config_thread_manager,
                 maintenance_running=maintenance._running,
                 threads=[{'name': item.name, 'daemon': item.daemon} for item in threading.enumerate()])

    config_app.app.router.lifespan_context = observed_lifespan
    emit('probe_started', fresh_manager_state=config_app.config_thread_manager.state.value,
         fresh_default_is_none=get_default_thread_manager() is None)
    uvicorn.run(config_app.app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
