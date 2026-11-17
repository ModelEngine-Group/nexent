# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual bidirectional AgentOS HTTP and PostgreSQL with owned test resources."""

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-KB-HTTP-D3-001")
def test_signed_knowledge_lifecycle(record_property, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [
        str(root),
        str(root / "backend"),
        str(root / "sdk"),
        str(Path(__file__).parent),
    ]
    import httpx
    import sqlalchemy as sa
    import uvicorn
    from contracts.agentos_knowledge import (
        KnowledgeFileDelete,
        KnowledgeFileUpload,
        KnowledgeJobLookup,
        KnowledgeOperation,
        ObjectReference,
    )
    from contracts.constants import environment
    from contracts.errors.exceptions import RuntimeUpstreamError
    from contracts.knowledge_cleanse import KnowledgeCleanseRequest
    from coordinator_probe import check_management_coordinator
    from fastapi import FastAPI
    from management.api.knowledge_base.agentos_authorization import (
        create_knowledge_authorization_router,
    )
    from management.services.file.cleanse_authorization import (
        KnowledgeCleanseAuthorization,
    )
    from management.services.file.cleanse_jobs import CleanseJobs
    from nexent.core.concurrency import (
        LanePolicy,
        ThreadManager,
        clear_default_thread_manager,
        set_default_thread_manager,
    )
    from nexent.storage.models import OperationContext, RecordQuery, StorageScope
    from runtime.agentos.knowledge import create_knowledge_router
    from runtime.agentos.middleware import AgentOSMiddleware
    from runtime.agentos.model import create_model_router
    from runtime.knowledge_base.service import KnowledgeService
    from runtime.model.service import ModelService
    from timeout_probe import check_lost_admission

    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.agentos_identity import ServicePrincipal, sign_call
    from infrastructure.rdb.account_record import (
        TenantGroupInfo,
        TenantGroupUser,
        UserAccount,
        UserTenant,
    )
    from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
    from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
    from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
    from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs, jobs
    from infrastructure.rdb.knowledge_search_records import KnowledgeRecord

    def docker(*args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=30
        ).strip()

    def context():
        return OperationContext("kb-http-" + uuid4().hex, time.monotonic() + 15)

    def lookup(state):
        return KnowledgeJobLookup(
            **state.model_dump(
                include={"knowledge_id", "file_id", "file_version", "job_id"}
            )
        )

    name = "dpr-kb-http-" + uuid4().hex
    container = engine = None
    ports = []
    sockets = []
    try:
        image_id = docker(
            "image", "inspect", "--format", "{{.Id}}", "postgres:15-alpine"
        )
        container = docker(
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::5432",
            "postgres:15-alpine",
        )
        deadline = time.monotonic() + 50
        while True:
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if ready.returncode == 0:
                break
            assert time.monotonic() < deadline, (
                "Owned database startup exceeded deadline"
            )
            time.sleep(0.2)
        port = json.loads(docker("inspect", container))[0]["NetworkSettings"]["Ports"][
            "5432/tcp"
        ][0]["HostPort"]
        engine = sa.create_engine(
            f"postgresql+psycopg2://postgres:fixture-password@127.0.0.1:{port}/postgres",
            connect_args={"connect_timeout": 2},
            hide_parameters=True,
        )
        for key, value in {
            "POSTGRES_USER": "postgres",
            "NEXENT_POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": port,
            "POSTGRES_DB": "postgres",
            "JWT_SECRET": "synthetic-kb-http-key",
        }.items():
            monkeypatch.setattr(environment, key, value)
        source = ObjectReference(
            space="files", key="source", version="etag:source", sha256="a" * 64
        )
        artifact = ObjectReference(
            space="files",
            key="artifacts/source/artifact.json",
            version="etag:artifact",
            sha256="b" * 64,
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA nexent")
            for table in (
                UserTenant.__table__,
                TenantGroupInfo.__table__,
                TenantGroupUser.__table__,
                UserAccount.__table__,
                KnowledgeRecord.__table__,
                KnowledgeFileLifecycle.__table__,
                cleanse_jobs,
            ):
                table.create(connection)
            connection.exec_driver_sql(
                (
                    root / "deploy/sql/migrations/v2.9.0_017_runtime_knowledge_jobs.sql"
                ).read_text(encoding="utf-8")
            )
            connection.execute(
                UserTenant.__table__.insert().values(
                    user_tenant_id=1,
                    user_id="user-a",
                    tenant_id="tenant-a",
                    delete_flag="N",
                )
            )
            connection.execute(
                UserAccount.__table__.insert().values(
                    account_id=1, user_id="user-a", user_roles=["DEV"], delete_flag="N"
                )
            )
            connection.execute(
                KnowledgeRecord.__table__.insert().values(
                    knowledge_id=1,
                    index_name="kb-one",
                    embedding_model_id=2,
                    tenant_id="tenant-a",
                    created_by="user-a",
                    delete_flag="N",
                )
            )
            connection.execute(
                KnowledgeFileLifecycle.__table__.insert().values(
                    file_id="a" * 32,
                    knowledge_id=1,
                    tenant_id="tenant-a",
                    index_name="kb-one",
                    original_filename="source.txt",
                    status="UPLOADED",
                    delete_flag="N",
                    source_generation=0,
                    source_space=source.space,
                    source_key=source.key,
                    source_revision=source.version,
                    source_sha256=source.sha256,
                )
            )
        resources = bind_cleanse_resources(
            StorageScope("management", "tenant-a", "user-a", set(TABLES)), engine
        )
        clean_records = bind_cleanse_jobs(
            StorageScope("management", "tenant-a", "user-a", {DATASET}), engine
        )
        records = bind_knowledge_jobs(
            StorageScope("runtime", "tenant-a", "user-a", {FILES, JOBS}), engine
        )
        ports.extend((resources, clean_records, records))
        cleanse = CleanseJobs(
            clean_records,
            authorize=KnowledgeCleanseAuthorization(
                resources, user_id="user-a"
            ).authorize,
            parser_version="v2",
        )
        clean_request = KnowledgeCleanseRequest(
            knowledge_id=1,
            file_id="a" * 32,
            file_version=0,
            source=source,
            filename="source.txt",
            idempotency_key="cleanse",
        )
        clean_state = cleanse.submit(clean_request, context=context())
        clean_handle = cleanse.claim(
            "parser-proof",
            job_id=clean_state.job_id,
            lease_seconds=30,
            context=context(),
        )
        assert cleanse.begin_execution(clean_handle, context=context())
        assert cleanse.transition(
            clean_handle, status="completed", artifact=artifact, context=context()
        )

        model_loads = []

        def load_model(model_id, tenant_id):
            model_loads.append((model_id, tenant_id))
            assert model_id == 2 and tenant_id == "tenant-a"
            return {
                "tenant_id": tenant_id,
                "model_type": "embedding",
                "delete_flag": "N",
                "update_time": "model-v1",
            }

        def no_provider(*args, **kwargs):
            raise AssertionError("Admission must not invoke a model provider")

        for _ in range(2):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            listener.setblocking(False)
            sockets.append(listener)
        management_url, runtime_url = (
            "http://127.0.0.1:" + str(listener.getsockname()[1]) for listener in sockets
        )

        def client(**kwargs):
            return httpx.AsyncClient(trust_env=False, **kwargs)

        management_app = FastAPI(root_path="/api")
        management_app.include_router(create_knowledge_authorization_router())
        runtime_app = FastAPI(root_path="/api")
        runtime_requests = []

        @runtime_app.middleware("http")
        async def observe_runtime_request(request, call_next):
            runtime_requests.append(request.url.path)
            return await call_next(request)

        runtime_app.add_middleware(AgentOSMiddleware)
        runtime_app.include_router(
            create_model_router(ModelService(load_model, no_provider))
        )
        runtime_app.include_router(
            create_knowledge_router(
                KnowledgeService(
                    AgentOSClient(management_url, client),
                    ModelService(load_model, no_provider),
                )
            )
        )

        async def scenario():
            manager = ThreadManager(
                service_name="kb-http-proof",
                lane_policies={
                    "control-io": LanePolicy(
                        name="control-io",
                        max_workers=4,
                        max_queue_size=8,
                        queue_timeout_seconds=0,
                        cancel_grace_seconds=2,
                        shutdown_grace_seconds=5,
                    ),
                },
            )
            manager.start()
            set_default_thread_manager(manager)
            servers, tasks = [], []
            try:
                for app, listener in zip((management_app, runtime_app), sockets):
                    server = uvicorn.Server(
                        uvicorn.Config(
                            app,
                            log_config=None,
                            access_log=False,
                            lifespan="off",
                            timeout_graceful_shutdown=3,
                        )
                    )
                    server.capture_signals = lambda: nullcontext()
                    servers.append(server)
                    tasks.append(asyncio.create_task(server.serve(sockets=[listener])))
                async with asyncio.timeout(10):
                    while not all(server.started for server in servers):
                        for task in tasks:
                            if task.done():
                                await task
                        await asyncio.sleep(0.01)
                api = AgentOSClient(runtime_url, client)
                request = KnowledgeFileUpload(
                    knowledge_id=1,
                    file_id="a" * 32,
                    file_version=0,
                    artifact=artifact,
                    parser_version="v2",
                    idempotency_key="upload",
                    embedding_model={"model_id": 2, "revision": "model-v1"},
                )
                first = await api.upload_knowledge_file(request, "user-a", "tenant-a")
                assert first.status == "queued"
                assert (
                    await api.upload_knowledge_file(request, "user-a", "tenant-a")
                    == first
                )
                assert (
                    await api.inspect_knowledge_file(
                        lookup(first), "user-a", "tenant-a"
                    )
                    == first
                )
                body = request.model_dump_json().encode()
                token = sign_call(
                    KnowledgeOperation.UPLOAD,
                    body,
                    ServicePrincipal("user-a", "tenant-a"),
                )
                async with httpx.AsyncClient(trust_env=False, timeout=10) as raw:
                    denied = await raw.post(
                        runtime_url + "/api" + KnowledgeOperation.UPLOAD.value,
                        content=body + b" ",
                        headers={"Authorization": "Bearer " + token},
                    )
                    assert denied.status_code == 401
                for payload, tenant, expected in (
                    (request, "other", 403),
                    (
                        request.model_copy(
                            update={
                                "artifact": artifact.model_copy(
                                    update={"key": "unconfirmed"}
                                )
                            }
                        ),
                        "tenant-a",
                        403,
                    ),
                    (
                        request.model_copy(
                            update={
                                "embedding_model": request.embedding_model.model_copy(
                                    update={"revision": "wrong"}
                                )
                            }
                        ),
                        "tenant-a",
                        409,
                    ),
                ):
                    with pytest.raises(RuntimeUpstreamError) as error:
                        await api.upload_knowledge_file(payload, "user-a", tenant)
                    assert error.value.status_code == expected

                def count_jobs():
                    return records.count(JOBS, RecordQuery(), context=context())

                # The direct record assertion runs outside the ASGI event loop below.
                assert len(model_loads) == 3
                with engine.begin() as connection:
                    connection.execute(
                        KnowledgeFileLifecycle.__table__.update().values(
                            status="DELETE_REQUESTED"
                        )
                    )
                delete = KnowledgeFileDelete(
                    knowledge_id=1,
                    file_id=request.file_id,
                    file_version=0,
                    idempotency_key="delete",
                )
                deleting = await api.delete_knowledge_file(delete, "user-a", "tenant-a")
                assert (
                    deleting.status == "cleanup_pending"
                    and not deleting.physical_cleanup_complete
                )
                assert (
                    await api.inspect_knowledge_file(
                        lookup(first), "user-a", "tenant-a"
                    )
                ).status == "cancelled"
                assert (
                    await api.inspect_knowledge_file(
                        lookup(deleting), "user-a", "tenant-a"
                    )
                ).status == "cleanup_pending"
                await check_lost_admission(api, engine, monkeypatch)
                with engine.connect() as connection:
                    assert (
                        connection.execute(
                            sa.select(sa.func.count()).select_from(jobs)
                        ).scalar_one()
                        == 3
                    )
                await check_management_coordinator(
                    api, engine, source, artifact, context, runtime_requests
                )
                with engine.begin() as connection:
                    connection.execute(
                        UserTenant.__table__.update().values(delete_flag="Y")
                    )
                with pytest.raises(RuntimeUpstreamError) as revoked:
                    await api.inspect_knowledge_file(
                        lookup(first), "user-a", "tenant-a"
                    )
                assert revoked.value.status_code == 403
                return count_jobs
            finally:
                try:
                    for server in servers:
                        server.should_exit = True
                    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
                finally:
                    drained = await manager.shutdown(timeout=5)
                    clear_default_thread_manager(manager)
                    assert not drained.stuck_execution_ids

        count = asyncio.run(scenario())
        assert count() == 4
        record_property(
            "knowledge_http_probe",
            json.dumps(
                {
                    "signed_bidirectional_http": True,
                    "live_management_authorization": True,
                    "durable_runtime_jobs": True,
                    "provider_invoked": False,
                    "physical_cleanup_claimed": False,
                    "management_coordinator_lost_reply_inspect_only": True,
                    "dependency_image_id": image_id,
                    "source_hashes": {
                        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                        for path in (
                            "backend/runtime/knowledge_base/service.py",
                            "backend/management/services/knowledge_base/authorization.py",
                            "infrastructure/agentos_client.py",
                            "backend/management/services/knowledge_base/ingestion_coordinator.py",
                        )
                    },
                },
                sort_keys=True,
            ),
        )
    finally:
        for listener in sockets:
            listener.close()
        for records in ports:
            records.close()
        if engine is not None:
            engine.dispose()
        remaining = docker("ps", "-aq", "--filter", "name=^/" + name + "$")
        if container is None and remaining:
            container = remaining
        if container is not None:
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "name=^/" + name + "$")
