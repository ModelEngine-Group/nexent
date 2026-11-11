# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""An independent cold reader process for the private capture integration fixture."""

import argparse
import json
import socket
from contextlib import asynccontextmanager

import uvicorn
from conftest import Catalog
from fastapi import FastAPI
from infrastructure.observability.trajectory_store import TrajectoryFileStore
from management.api.observability import trajectory as api
from management.services.trajectory.primitives import ReferenceStore
from management.services.trajectory.service import TrajectoryService
from nexent.core.concurrency import LanePolicy, ThreadManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--fd', required=True, type=int)
    arguments = parser.parse_args()
    listener = socket.socket(fileno=arguments.fd)
    manager = ThreadManager('cold-reader', {'trajectory-read': LanePolicy('trajectory-read', 2, 2)})

    @asynccontextmanager
    async def lifespan(app):
        manager.start()
        print(json.dumps({'port': listener.getsockname()[1]}), flush=True)
        try:
            yield
        finally:
            await manager.shutdown(timeout=3)
            assert manager.snapshot().active_count == 0
            print(json.dumps({'closed': True, 'active_workers': 0}), flush=True)

    store = TrajectoryFileStore(arguments.root, authorize=lambda _: None)
    service = TrajectoryService(store, Catalog(), ReferenceStore())
    api.get_service = lambda: service
    api.get_current_user_context = lambda header: (
        ('admin', 'tenant', 'ADMIN') if header == 'admin' else ('owner', 'tenant', 'USER')
    )
    app = FastAPI(lifespan=lifespan)
    app.state.thread_manager = manager
    app.include_router(api.router)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == '__main__':
    main()
