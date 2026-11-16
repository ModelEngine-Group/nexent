# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run inside the owned Linux dependency container, using real product startup IPC."""

import asyncio
import json
import os

import httpx
import psutil
import sqlalchemy as sa
from contracts.constants import environment
from fastapi import FastAPI
from management.services.file.cleanse_lifespan import cleanse_lifespan

from backend.http.server.health import install_health_contract
from infrastructure.file_processing.root_process import CleanseProcess
from infrastructure.rdb.cleanse_jobs import cleanse_jobs


async def main():
    engine = sa.create_engine(
        sa.URL.create(
            "postgresql+psycopg2",
            username=environment.POSTGRES_USER,
            password=environment.NEXENT_POSTGRES_PASSWORD,
            host=environment.POSTGRES_HOST,
            port=int(environment.POSTGRES_PORT),
            database=environment.POSTGRES_DB,
        ),
        hide_parameters=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA nexent")
        cleanse_jobs.create(connection)
    created = []

    def factory():
        owner = CleanseProcess()
        created.append(owner)
        return owner

    app = FastAPI()
    install_health_contract(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://local"
    ) as client:
        try:
            async with cleanse_lifespan(app, enabled=True, factory=factory):
                owner = app.state.cleanse_root
                pid = owner.process.pid
                monitor = app.state.required_background_tasks[-1]
                assert pid != os.getpid() and psutil.pid_exists(pid)
                assert (
                    "management.services.file.cleanse_root"
                    in psutil.Process(pid).cmdline()
                )
                assert (await client.get("/health/ready")).status_code == 200
                assert not monitor.done()
            assert owner.process.returncode == 0 and not psutil.pid_exists(pid)
            assert monitor.cancelled() and len(created) == 1
            async with cleanse_lifespan(app, enabled=True, factory=factory):
                failed_owner = app.state.cleanse_root
                failed_pid = failed_owner.process.pid
                failed = app.state.required_background_tasks[-1]
                with engine.begin() as connection:
                    cleanse_jobs.drop(connection)
                try:
                    await asyncio.wait_for(asyncio.shield(failed), 15)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError(
                        "discovery failure did not end the health monitor"
                    )
                assert failed.done() and failed_owner.process.returncode != 0
                assert (await client.get("/health/ready")).status_code == 503
                await asyncio.sleep(0.1)
                assert len(created) == 2 and failed_owner.process.pid == failed_pid
            assert not psutil.pid_exists(failed_pid)
            assert not app.state.required_background_tasks
        finally:
            engine.dispose()
    print(
        json.dumps(
            {
                "separate_ready": True,
                "root_reaped": True,
                "failure_unhealthy": True,
                "no_restart": True,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
