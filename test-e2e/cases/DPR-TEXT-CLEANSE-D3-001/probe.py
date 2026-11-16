# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Two signed HTTP directions and real PG/MinIO; parser/model are controlled ports."""

import asyncio
import io
import json
import socket
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import boto3
import httpx
import sqlalchemy as sa
import uvicorn
from botocore.config import Config
from contracts.agentos import AgentToolInvocation, ToolBinding
from contracts.constants import environment
from contracts.knowledge_cleanse import parse_cleanse_request
from fastapi import FastAPI, Response
from management.api.file.agentos_cleanse import create_file_cleanse_router
from management.services.file.cleanse_executor import CleanseExecutor
from management.services.file.run_cleanse_service import FileCleanseService
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import NotFound
from nexent.storage.models import ObjectRef, OperationContext
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.agentos.tools import create_tool_router

from infrastructure.agentos_client import AgentOSClient
from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.file_processing.text_objects import bind_text_artifact
from infrastructure.object_storage.composition import bind_source_objects
from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.cleanse_jobs import cleanse_jobs


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=25
    ).strip()


def context():
    return OperationContext("text-probe", time.monotonic() + 20)


class Parser:
    def ensure_initialized(self):
        pass

    def file_structure(self, *, file_data, filename):
        if filename.endswith(".json"):
            return [
                {
                    "content": "",
                    "metadata": {"element_type": "JSONSource", "source_format": "json"},
                }
            ], []
        return [
            {
                "content": file_data.decode(),
                "metadata": {"element_type": "NarrativeText"},
            }
        ], [
            {"image_bytes": b"controlled-image", "image_format": "png"},
        ]


class DrivenCleanseService(FileCleanseService):
    """Replace only process scheduling/native parser; retain production jobs and objects."""

    def __init__(self):
        super().__init__(parser_version="controlled-parser")
        self.produced = []

    def inspect(self, lookup, *, tenant_id, user_id, context):
        state = super().inspect(
            lookup, tenant_id=tenant_id, user_id=user_id, context=context
        )
        if state.status == "queued":
            with self._jobs(tenant_id, user_id, context) as jobs:
                row = jobs.claim(
                    "probe-executor",
                    job_id=lookup.job_id,
                    lease_seconds=60,
                    context=context,
                )
                assert row is not None
                request = parse_cleanse_request(row)
                objects = bind_cleanse_objects(
                    tenant_id, user_id, request.source, context=context, run=lookup
                )
                executor = CleanseExecutor(
                    runtime=Parser(),
                    objects=objects,
                    parser_version=self.parser_version,
                )
                try:
                    artifact = executor(row, request, context=context)
                    self.produced.append((lookup, request.source, artifact))
                    assert jobs.transition(
                        row, status="completed", artifact=artifact, context=context
                    )
                finally:
                    executor.close()
            state = super().inspect(
                lookup, tenant_id=tenant_id, user_id=user_id, context=context
            )
        return state


def main(run_id):
    assert len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)
    containers, servers, sockets = [], [], []
    engine = original = foreign = manager = None
    evidence = {}
    try:

        def start(image, port, *args):
            image_id = docker("image", "inspect", "--format", "{{.Id}}", image)
            container = docker(
                "run",
                "--rm",
                "-d",
                "--label",
                "nexent.test_run=" + run_id,
                "-p",
                f"127.0.0.1::{port}",
                *args,
                image,
                *(["server", "/data"] if port == 9000 else []),
            )
            containers.append(container)
            mapping = json.loads(docker("inspect", container))[0]["NetworkSettings"][
                "Ports"
            ][f"{port}/tcp"][0]
            return "127.0.0.1:" + mapping["HostPort"], image_id

        pg, pg_id = start(
            "postgres:15-alpine", 5432, "-e", "POSTGRES_PASSWORD=fixture-password"
        )
        minio, minio_id = start(
            "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z",
            9000,
            "-e",
            "MINIO_ROOT_USER=fixture-user",
            "-e",
            "MINIO_ROOT_PASSWORD=fixture-password",
        )
        engine = sa.create_engine(
            "postgresql+psycopg2://postgres:fixture-password@" + pg + "/postgres",
            connect_args={"connect_timeout": 1},
            hide_parameters=True,
        )
        deadline = time.monotonic() + 45
        while True:
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
                with httpx.Client(trust_env=False, timeout=1) as client:
                    if (
                        client.get(
                            "http://" + minio + "/minio/health/ready"
                        ).status_code
                        == 200
                    ):
                        break
            except (sa.exc.OperationalError, httpx.HTTPError):
                pass
            assert time.monotonic() < deadline
            time.sleep(0.1)
        client = boto3.client(
            "s3",
            endpoint_url="http://" + minio,
            aws_access_key_id="fixture-user",
            aws_secret_access_key="fixture-password",
            region_name="us-east-1",
            config=Config(
                retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}
            ),
        )
        try:
            client.create_bucket(Bucket="text-proof")
        finally:
            client.close()
        for key, value in {
            "POSTGRES_USER": "postgres",
            "NEXENT_POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_HOST": engine.url.host,
            "POSTGRES_PORT": str(engine.url.port),
            "POSTGRES_DB": "postgres",
            "MINIO_ENDPOINT": "http://" + minio,
            "MINIO_ACCESS_KEY": "fixture-user",
            "MINIO_SECRET_KEY": "fixture-password",
            "MINIO_DEFAULT_BUCKET": "text-proof",
            "MINIO_REGION": "us-east-1",
            "JWT_SECRET": "synthetic-text-proof-key",
        }.items():
            setattr(environment, key, value)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA nexent")
            for table in (UserTenant.__table__, UserAccount.__table__, cleanse_jobs):
                table.create(connection)
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
        original = bind_source_objects(
            "tenant-a", "user-a", "attachments/user-a/original.txt", "text-proof"
        )
        original.put(
            ObjectRef("files", "attachments/user-a/original.txt"),
            io.BytesIO(b"original"),
            content_type="text/plain",
            size=8,
            context=context(),
        )
        foreign_key = "workspace/user-a/" + "f" * 32 + "/outputs/analysis/sentinel.txt"
        foreign = bind_source_objects("tenant-a", "user-a", foreign_key, "text-proof")
        foreign.put(
            ObjectRef("files", foreign_key),
            io.BytesIO(b"foreign"),
            content_type="text/plain",
            size=7,
            context=context(),
        )
        service = DrivenCleanseService()
        management = FastAPI(root_path="/api")
        management.include_router(create_file_cleanse_router(service))

        @management.get("/source/{kind}")
        async def source(kind: str):
            return Response(
                b'{"sentinel":"json preserved"}'
                if kind == "json"
                else b"Text sentinel preserved."
            )

        def listen(app):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            sock.setblocking(False)
            sockets.append(sock)
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
            return "http://127.0.0.1:" + str(sock.getsockname()[1])

        management_url = listen(management)
        environment.MANAGEMENT_AGENTOS_URL = management_url
        captured = []

        def analyze(**kwargs):
            captured.append(kwargs["text_content"])
            return SimpleNamespace(content="analyzed"), 0

        record = {
            "model_id": 9,
            "tenant_id": "tenant-a",
            "delete_flag": "N",
            "model_type": "llm",
            "update_time": "v1",
        }

        async def scenario():
            nonlocal manager
            manager = ThreadManager(
                service_name="text-proof",
                lane_policies={
                    name: LanePolicy(
                        name=name,
                        max_workers=4,
                        max_queue_size=4,
                        queue_timeout_seconds=0,
                        cancel_grace_seconds=2,
                        shutdown_grace_seconds=5,
                    )
                    for name in ("control-io", "model-tool-io")
                },
            )
            manager.start()
            set_default_thread_manager(manager)
            runtime = FastAPI(root_path="/api")
            runtime.add_middleware(AgentOSMiddleware)
            runtime.include_router(create_tool_router(manager))
            runtime_url = listen(runtime)
            tasks = [
                asyncio.create_task(server.serve(sockets=[sock]))
                for server, sock in zip(servers, sockets)
            ]
            try:
                async with asyncio.timeout(10):
                    while not all(server.started for server in servers):
                        await asyncio.sleep(0.01)
                api = AgentOSClient(
                    runtime_url,
                    lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs),
                )
                for index, kind in enumerate(("text", "json")):
                    result = await api.invoke_tool(
                        AgentToolInvocation(
                            run_id=("a" if index == 0 else "b") * 32,
                            tool=ToolBinding(
                                tool_id="analyze_text_file",
                                version="1",
                                parameters={
                                    "description": {},
                                    "selected_model_id": 9,
                                    "model": {"model_id": 9, "revision": "v1"},
                                },
                            ),
                            inputs={
                                "file_url_list": [management_url + "/source/" + kind],
                                "query": "analyze",
                            },
                        ),
                        "user-a",
                        "tenant-a",
                    )
                    assert result.result == ["analyzed"]
                assert captured[0] == "Text sentinel preserved."
                assert "json preserved" in captured[1] and "sentinel" in captured[1]
                assert len(service.produced) == 2

                def verify():
                    original.stat(
                        ObjectRef("files", "attachments/user-a/original.txt"),
                        context=context(),
                    )
                    foreign.stat(ObjectRef("files", foreign_key), context=context())
                    from infrastructure.object_storage.composition import (
                        _configured_client,
                    )

                    oracle = _configured_client(10)
                    try:
                        for lookup, _, _ in service.produced:
                            assert not oracle.list_objects_v2(
                                Bucket="text-proof",
                                Prefix=f"tenant-a/run-cleanse/{lookup.run_id}/{lookup.job_id}/",
                            ).get("Contents")
                    finally:
                        oracle.close()
                    for lookup, source_ref, artifact in service.produced:
                        assert (
                            service.inspect(
                                lookup,
                                tenant_id="tenant-a",
                                user_id="user-a",
                                context=context(),
                            ).status
                            == "released"
                        )
                        source_port = bind_source_objects(
                            "tenant-a",
                            "user-a",
                            source_ref.key,
                            "text-proof",
                            writable=False,
                        )
                        from infrastructure.agentos_identity import ServicePrincipal

                        artifacts = bind_text_artifact(
                            ServicePrincipal("user-a", "tenant-a"),
                            lookup,
                            source_ref,
                            artifact,
                        )
                        try:
                            for port, ref in (
                                (source_port, ObjectRef("files", source_ref.key)),
                                (artifacts, ObjectRef("files", artifact.key)),
                            ):
                                try:
                                    port.stat(ref, context=context())
                                except NotFound:
                                    pass
                                else:
                                    raise AssertionError("Temporary object remains")
                        finally:
                            source_port.close()
                            artifacts.close()

                from nexent.core.concurrency import ManagedTaskSpec

                await manager.run(
                    "control-io",
                    ManagedTaskSpec(task_name="verify", owner="test"),
                    verify,
                )
                evidence.update(
                    signed_both_directions=True,
                    sdk_model_inputs=True,
                    text_and_json=True,
                    released_jobs=2,
                    original_preserved=True,
                    foreign_preserved=True,
                    private_cleanup=True,
                )
            finally:
                for server in servers:
                    server.should_exit = True
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
                drained = await manager.shutdown(timeout=5)
                clear_default_thread_manager(manager)
                assert not drained.stuck_execution_ids

        with (
            patch(
                "runtime.agentos.prepared_analysis.get_model_by_model_id",
                return_value=record,
            ),
            patch(
                "infrastructure.model_adapter.build_adapter_fresh",
                return_value=SimpleNamespace(analyze_long_text=analyze),
            ),
        ):
            asyncio.run(scenario())
        evidence["dependency_images"] = {"pg": pg_id, "minio": minio_id}
    finally:
        for sock in sockets:
            sock.close()
        if foreign is not None:
            foreign.close()
        if original is not None:
            original.close()
        if engine is not None:
            engine.dispose()
        for container in reversed(containers):
            docker("rm", "-f", "-v", container)
    evidence["owned_cleanup"] = not docker(
        "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id
    )
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
