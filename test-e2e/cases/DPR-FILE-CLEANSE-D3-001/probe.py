# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real signed Management admission and scoped PostgreSQL task state."""

import asyncio
import json
import socket
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import httpx
import sqlalchemy as sa
import uvicorn
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from fastapi import FastAPI
from management.api.file.agentos_cleanse import create_file_cleanse_router
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.cleanse_jobs import cleanse_jobs


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=20).strip()


def main(run_id):
    assert len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)
    image = "postgres:15-alpine"
    image_id = docker("image", "inspect", "--format", "{{.Id}}", image)
    container = engine = listener = None
    evidence = {}
    try:
        container = docker("run", "--rm", "-d", "--label", "nexent.test_run=" + run_id,
                           "-e", "POSTGRES_PASSWORD=fixture-password", "-p", "127.0.0.1::5432", image)
        mapping = json.loads(docker("inspect", container))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]
        port = mapping["HostPort"]
        engine = sa.create_engine("postgresql+psycopg2://postgres:fixture-password@127.0.0.1:" + port + "/postgres",
                                  connect_args={"connect_timeout": 1}, hide_parameters=True)
        deadline = time.monotonic() + 30
        while True:
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
                break
            except sa.exc.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        for name, value in {
            "POSTGRES_USER": "postgres", "NEXENT_POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": port, "POSTGRES_DB": "postgres",
            "JWT_SECRET": "synthetic-run-cleanse-proof",
        }.items():
            setattr(environment, name, value)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA nexent")
            for table in (UserTenant.__table__, UserAccount.__table__, cleanse_jobs):
                table.create(connection)
            connection.execute(UserTenant.__table__.insert().values(
                user_tenant_id=1, user_id="user-a", tenant_id="tenant-a", delete_flag="N",
            ))
            connection.execute(UserAccount.__table__.insert().values(
                account_id=1, user_id="user-a", user_roles=["DEV"], delete_flag="N",
            ))
        app = FastAPI(root_path="/api")
        app.include_router(create_file_cleanse_router())
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        request = FileCleanseRequest(
            run_id="a" * 32, filename="source.txt", idempotency_key="extract-1",
            source=ObjectReference(space="files", key="attachments/user-a/source.txt",
                                   version="etag:synthetic", sha256="b" * 64),
        )

        async def scenario():
            manager = ThreadManager(service_name="file-cleanse-proof", lane_policies={
                "control-io": LanePolicy(name="control-io", max_workers=4, max_queue_size=4,
                                         queue_timeout_seconds=0, cancel_grace_seconds=2, shutdown_grace_seconds=5),
            })
            manager.start()
            set_default_thread_manager(manager)
            server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="off",
                                                   timeout_graceful_shutdown=3))
            server.capture_signals = lambda: nullcontext()
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            statuses = []

            async def observed(response):
                statuses.append(response.status_code)

            client = AgentOSClient(url, lambda **kwargs: httpx.AsyncClient(
                trust_env=False, event_hooks={"response": [observed]}, **kwargs,
            ))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.01)
                state = await client.submit_file_cleanse(request, "user-a", "tenant-a")
                assert state.status == "queued" and state.artifact is None
                assert await client.submit_file_cleanse(request, "user-a", "tenant-a") == state
                lookup = FileCleanseLookup(run_id=state.run_id, job_id=state.job_id)
                assert await client.inspect_file_cleanse(lookup, "user-a", "tenant-a") == state
                assert statuses == [202, 202, 200]

                async def rejected(method, payload, user, tenant, expected):
                    try:
                        await method(payload, user, tenant)
                        raise AssertionError("Invalid request was accepted")
                    except RuntimeUpstreamError as error:
                        assert error.status_code == expected

                await rejected(client.submit_file_cleanse, request.model_copy(update={"filename": "changed.txt"}),
                               "user-a", "tenant-a", 409)
                await rejected(client.release_file_cleanse, lookup, "user-a", "tenant-a", 409)
                await rejected(client.submit_file_cleanse, request.model_copy(update={
                    "source": request.source.model_copy(update={"key": "attachments/user-b/source.txt"}),
                }), "user-a", "tenant-a", 403)
                for user, tenant in (("user-b", "tenant-a"), ("user-a", "tenant-b")):
                    for operation in (client.inspect_file_cleanse, client.cancel_file_cleanse, client.release_file_cleanse):
                        await rejected(operation, lookup, user, tenant, 403)
                await rejected(client.inspect_file_cleanse, lookup.model_copy(update={"run_id": "c" * 32}),
                               "user-a", "tenant-a", 404)
                body = request.model_dump_json().encode()
                token = sign_call(ManagementOperation.FILE_CLEANSE, body, ServicePrincipal("user-a", "tenant-a"))
                async with httpx.AsyncClient(trust_env=False) as http:
                    response = await http.post(url + "/api" + ManagementOperation.FILE_CLEANSE.value,
                                               content=body + b" ", headers={"Authorization": "Bearer " + token})
                assert response.status_code == 401
                cancelled = await client.cancel_file_cleanse(lookup, "user-a", "tenant-a")
                assert cancelled.status == "cancelled"
                assert await client.cancel_file_cleanse(lookup, "user-a", "tenant-a") == cancelled
                with engine.begin() as connection:
                    rows = connection.execute(sa.select(cleanse_jobs)).mappings().all()
                    assert len(rows) == 1
                    row = rows[0]
                    assert (row["tenant_id"], row["user_id"], row["run_id"], row["scope_kind"]) == (
                        "tenant-a", "user-a", request.run_id, "run",
                    )
                    assert row["request_payload"] == request.model_dump(mode="json")
                    assert row["status"] == "cancelled" and row["artifact"] is None
                    # Controlled released fixture proves protocol replay, not physical deletion.
                    connection.execute(cleanse_jobs.update().where(cleanse_jobs.c.id == row["id"]).values(status="released"))
                receipt = await client.release_file_cleanse(lookup, "user-a", "tenant-a")
                assert receipt.released and receipt.job_id == lookup.job_id and receipt.run_id == lookup.run_id
                assert await client.release_file_cleanse(lookup, "user-a", "tenant-a") == receipt
                assert (await client.inspect_file_cleanse(lookup, "user-a", "tenant-a")).status == "released"
                await rejected(client.release_file_cleanse, lookup.model_copy(update={"run_id": "c" * 32}), "user-a", "tenant-a", 404)
                with engine.begin() as connection:
                    connection.execute(UserTenant.__table__.update().values(delete_flag="Y"))
                for operation in (client.inspect_file_cleanse, client.cancel_file_cleanse, client.release_file_cleanse):
                    await rejected(operation, lookup, "user-a", "tenant-a", 403)
                evidence.update(scoped_admission=True, identity_denial=True, idempotent_cancel=True,
                                live_revocation=True, pg_rows=1, source_pinned=True, http_statuses=statuses,
                                signed_release=True)
            finally:
                server.should_exit = True
                await asyncio.wait_for(serving, timeout=5)
                drained = await manager.shutdown(timeout=5)
                clear_default_thread_manager(manager)
                assert not drained.stuck_execution_ids

        asyncio.run(scenario())
    finally:
        if listener is not None:
            listener.close()
        if engine is not None:
            engine.dispose()
        if container is not None:
            docker("rm", "-f", "-v", container)
    assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    evidence.update(owned_cleanup=True, dependency_image=image_id)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
