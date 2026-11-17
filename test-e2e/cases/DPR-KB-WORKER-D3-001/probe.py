# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute Runtime uploads over real storage and live signed Management grants."""

import asyncio
import hashlib
import io
import json
import socket
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import httpx
import uvicorn
from contracts.agentos_knowledge import (
    KnowledgeFileUpload,
    KnowledgeJobLookup,
    ObjectReference,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from deletion_probe import prove_deletion
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from management.services.file.cleanse import cleanse_object
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.cleanse_jobs import CleanseJobs
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.models import (
    Comparison,
    ObjectRef,
    OperationContext,
    Revision,
    StorageScope,
    VectorKey,
)
from runtime.agentos.knowledge import create_knowledge_router
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.knowledge_base.deletion import KnowledgeDeleteWorker
from runtime.knowledge_base.dispatch import knowledge_lifespan
from runtime.knowledge_base.jobs import KnowledgeJobs
from runtime.knowledge_base.search import KnowledgeSearchService
from runtime.knowledge_base.service import KnowledgeService
from runtime.knowledge_base.tool_search import KnowledgeToolSearch
from runtime.knowledge_base.worker import KnowledgeUploadWorker
from runtime.model.service import ModelService
from search_probe import prove_deleted_search, prove_search
from stores import Stores

from backend.http.server.health import install_health_contract
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.knowledge_vectors import bind_knowledge_vectors
from infrastructure.object_storage.composition import bind_source_objects
from infrastructure.rdb.account_record import (
    TenantGroupInfo,
    TenantGroupUser,
    UserAccount,
    UserTenant,
)
from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord


def context():
    return OperationContext("worker-probe", time.monotonic() + 30)


def lookup(state):
    return KnowledgeJobLookup(
        **state.model_dump(
            include={"knowledge_id", "file_id", "file_version", "job_id"}
        )
    )


def main(run_id):
    assert len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)
    stores = Stores(run_id)
    owned, listener = [], None
    evidence = {}
    try:
        for key, value in stores.start().items():
            setattr(environment, key, value)
        engine = stores.engine
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
                    index_name="kb-worker",
                    embedding_model_id=2,
                    knowledge_sources="elasticsearch",
                    tenant_id="tenant-a",
                    created_by="user-a",
                    delete_flag="N",
                )
            )
        content = b"Runtime owned worker integration"
        objects = bind_source_objects("tenant-a", "user-a", "source", "worker-files")
        owned.append(objects)
        metadata = objects.put(
            ObjectRef("files", "source"),
            io.BytesIO(content),
            content_type="text/plain",
            size=len(content),
            context=context(),
        )
        source = ObjectReference(
            space="files",
            key="source",
            version=metadata.ref.version.value,
            sha256=metadata.sha256,
        )
        outputs = bind_cleanse_objects("tenant-a", "user-a", source, context=context())
        owned.append(outputs)
        parser = SimpleNamespace(
            file_structure=lambda **kwargs: ([{"content": content.decode()}], [])
        )
        artifact = cleanse_object(
            source,
            "source.txt",
            "v2",
            parser=parser,
            objects=outputs,
            context=context(),
        )
        with engine.begin() as connection:
            for file_id in ("a" * 32, "b" * 32):
                connection.execute(
                    KnowledgeFileLifecycle.__table__.insert().values(
                        file_id=file_id,
                        knowledge_id=1,
                        tenant_id="tenant-a",
                        index_name="kb-worker",
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
        owned.extend((resources, clean_records, records))
        clean_policy = CleanseJobs(
            clean_records,
            authorize=KnowledgeCleanseAuthorization(
                resources, user_id="user-a"
            ).authorize,
            parser_version="v2",
        )
        for file_id in ("a" * 32, "b" * 32):
            request = KnowledgeCleanseRequest(
                knowledge_id=1,
                file_id=file_id,
                file_version=0,
                source=source,
                filename="source.txt",
                idempotency_key="cleanse",
            )
            state = clean_policy.submit(request, context=context())
            handle = clean_policy.claim(
                "parser", job_id=state.job_id, lease_seconds=30, context=context()
            )
            assert clean_policy.begin_execution(handle, context=context())
            assert clean_policy.transition(
                handle, status="completed", artifact=artifact, context=context()
            )
        stores.legacy.index(
            index="kb-worker",
            id="legacy-sentinel",
            document={"content": "legacy remains"},
            refresh="wait_for",
        )
        calls, searches = [], []

        def load_record(model_id, tenant_id):
            assert model_id in {2, 3} and tenant_id == "tenant-a"
            return {
                "tenant_id": tenant_id,
                "delete_flag": "N",
                "model_type": "embedding" if model_id == 2 else "rerank",
                "max_tokens": 2,
                "update_time": "v1",
            }

        class Adapter:
            def __init__(self, modality):
                self.modality = modality

            async def invoke(self, request):
                if self.modality == "rerank":
                    searches.append("rerank")
                    assert request.documents == [content.decode()]
                    return [{"index": 0, "relevance_score": 0.98}]
                if request.inputs == ["worker"]:
                    searches.append("embedding")
                    return [[1.0, 0.5]]
                calls.append(request.inputs)
                if len(calls) == 2:
                    with engine.begin() as connection:
                        connection.execute(
                            UserTenant.__table__.update().values(delete_flag="Y")
                        )
                return [[1.0, 0.5] for _ in request.inputs]

        def build_adapter(record, modality, slot, tenant_id):
            assert modality == slot and modality in {"embedding", "rerank"} and tenant_id == "tenant-a"
            return Adapter(modality)

        models = ModelService(load_record, build_adapter)
        app = FastAPI(root_path="/api")
        app.include_router(create_knowledge_authorization_router())
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        rpc = AgentOSClient(
            "http://127.0.0.1:" + str(listener.getsockname()[1]),
            lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs),
        )
        api = KnowledgeService(rpc, models)
        worker = KnowledgeUploadWorker(
            rpc, models, max_artifact_bytes=1024 * 1024, max_source_bytes=1024 * 1024
        )
        workers = {"upload": worker, "delete": KnowledgeDeleteWorker(rpc)}
        actor = ServicePrincipal("user-a", "tenant-a")

        async def scenario():
            manager = ThreadManager(
                service_name="kb-worker-proof",
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
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            health_app = FastAPI(root_path="/api", lifespan=lambda app: knowledge_lifespan(app, workers=workers))
            health_app.add_middleware(AgentOSMiddleware)
            health_app.include_router(create_knowledge_router(api))
            install_health_contract(health_app)
            health_socket = socket.socket()
            health_socket.bind(("127.0.0.1", 0))
            health_socket.listen(128)
            health_socket.setblocking(False)
            health_url = "http://127.0.0.1:" + str(health_socket.getsockname()[1])
            public = AgentOSClient(health_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
            health_server = uvicorn.Server(uvicorn.Config(
                health_app, log_config=None, access_log=False, lifespan="on",
                timeout_graceful_shutdown=3,
            ))
            health_server.capture_signals = lambda: nullcontext()
            health_serving = asyncio.create_task(health_server.serve(sockets=[health_socket]))

            async def db(action, *args, **kwargs):
                return await manager.run(
                    "control-io",
                    ManagedTaskSpec(task_name="worker-observation", owner="test"),
                    action,
                    *args,
                    **kwargs,
                )

            try:
                async with asyncio.timeout(10):
                    while not server.started or not health_server.started:
                        if serving.done():
                            await serving
                        if health_serving.done():
                            await health_serving
                        await asyncio.sleep(0.01)
                async with httpx.AsyncClient(trust_env=False) as health:
                    assert (await health.get(health_url + "/health/ready")).status_code == 200
                request = KnowledgeFileUpload(
                    knowledge_id=1,
                    file_id="a" * 32,
                    file_version=0,
                    artifact=artifact,
                    parser_version="v2",
                    idempotency_key="upload",
                    embedding_model={"model_id": 2, "revision": "v1"},
                    chunking_strategy="none",
                )
                admitted = await api.upload(request, actor)
                async with asyncio.timeout(15):
                    while True:
                        completed = await api.inspect(lookup(admitted), actor)
                        if completed.status == "completed":
                            break
                        task, = health_app.state.required_background_tasks
                        if task.done():
                            raise task.exception() or AssertionError("Dispatch stopped")
                        await asyncio.sleep(0.02)
                assert completed.status == "completed"
                assert (
                    await worker.process(lookup(admitted), actor, owner_id="worker-two")
                    == completed
                )
                assert calls == [[content.decode()]]
                row = await db(records.get, JOBS, admitted.job_id, context=context())
                policy = KnowledgeJobs(records, authorize=lambda *args, **kwargs: None)
                assert await db(
                    policy.is_visible,
                    lookup(admitted),
                    row["attempt_id"],
                    context=context(),
                )
                vectors = bind_knowledge_vectors(actor, "kb-worker", 2)
                owned.append(vectors)
                assert (
                    await db(vectors.count, "kb-worker", None, context=context()) == 1
                )
                vector = await db(
                    vectors.get,
                    VectorKey("kb-worker", "1/" + request.file_id + "/0/0"),
                    context=context(),
                )
                assert vector.generation == Revision(row["attempt_id"])
                assert vector.payload["content"] == content.decode()
                assert vector.payload["embedding_revision"] == "v1"
                evidence.update(await prove_search(public, actor, request, content.decode(), searches))
                search_service = KnowledgeSearchService(rpc, models)
                from contracts.agentos_knowledge import KnowledgeSearchAuthorization
                grant = await rpc.authorize_knowledge_search(
                    KnowledgeSearchAuthorization(knowledge_ids=[1]), actor.user_id, actor.tenant_id)
                bindings = [(grant.knowledge_bases[0], request.embedding_model)]
                bound = KnowledgeToolSearch(search_service, actor, bindings, file_ids=[request.file_id])
                hits = await bound.search("worker", ["kb-worker"], search_mode="accurate")
                assert len(hits) == 1 and hits[0].file_id == request.file_id
                assert hits[0].content == content.decode() and hits[0].file_version == 0
                denied = KnowledgeToolSearch(search_service, actor, bindings, file_ids=[])
                assert await denied.search("worker", ["kb-worker"]) == []
                evidence["bound_tool_search"] = True
                evidence.update(await prove_deletion(
                    api, actor, request, vectors, vector, workers, db, owned, calls,
                ))
                evidence.update(await prove_deleted_search(public, actor, request, searches))
                rejected = await api.upload(
                    request.model_copy(update={"file_id": "b" * 32}), actor
                )
                task, = health_app.state.required_background_tasks
                async with asyncio.timeout(15):
                    await asyncio.wait({task}, return_when=asyncio.ALL_COMPLETED)
                error = task.exception()
                assert isinstance(error, RuntimeUpstreamError) and error.status_code == 403
                async with httpx.AsyncClient(trust_env=False) as health:
                    assert (await health.get(health_url + "/health/ready")).status_code == 503
                    assert (await health.get(health_url + "/health/live")).status_code == 200
                failed = await db(records.get, JOBS, rejected.job_id, context=context())
                assert (
                    failed["status"] == "failed"
                    and failed["writer_ended"]
                    and not failed["reconcile_required"]
                )
                assert not await db(
                    policy.is_visible,
                    lookup(rejected),
                    failed["attempt_id"],
                    context=context(),
                )
                assert (
                    await db(
                        vectors.count,
                        "kb-worker",
                        Comparison("file_id", "eq", "b" * 32),
                        context=context(),
                    )
                    == 0
                )
                assert len(calls) == 2
                evidence.update(
                    pinned_objects=True,
                    visible_generation=True,
                    duplicate_no_invoke=True,
                    revocation_before_write=True,
                    lifespan_discovery=True,
                    failed_readiness=True,
                )
            finally:
                try:
                    server.should_exit = True
                    health_server.should_exit = True
                    await asyncio.wait_for(asyncio.gather(serving, health_serving), timeout=5)
                finally:
                    health_socket.close()
                    drained = await manager.shutdown(timeout=5)
                    clear_default_thread_manager(manager)
                    assert not drained.stuck_execution_ids

        asyncio.run(scenario())
        assert (
            stores.legacy.get(index="kb-worker", id="legacy-sentinel")["_source"][
                "content"
            ]
            == "legacy remains"
        )
        evidence.update(
            legacy_preserved=True,
            dependency_images=stores.images,
            source_hashes={
                path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                for path in (
                    "backend/runtime/knowledge_base/worker.py",
                    "backend/runtime/knowledge_base/search.py",
                    "backend/management/services/knowledge_base/search_authorization.py",
                    "backend/management/services/knowledge_base/file_authorization.py",
                    "backend/contracts/agentos_knowledge.py",
                    "backend/runtime/agentos/knowledge.py",
                    "backend/management/api/knowledge_base/agentos_authorization.py",
                    "infrastructure/agentos_client.py",
                    "backend/runtime/knowledge_base/dispatch.py",
                    "backend/runtime/knowledge_base/deletion.py",
                    "backend/runtime/knowledge_base/jobs.py",
                    "backend/runtime/knowledge_base/ingestion.py",
                    "backend/runtime/api/application.py",
                    "infrastructure/knowledge_cleanse.py",
                    "infrastructure/knowledge_objects.py",
                    "infrastructure/knowledge_vectors.py",
                    "infrastructure/knowledge_runtime.py",
                    "infrastructure/rdb/knowledge_dispatch.py",
                    "infrastructure/rdb/cleanse_resources.py",
                    "infrastructure/vdb/vector_schema.py",
                    "infrastructure/vdb/vector_store.py",
                )
            },
        )
    finally:
        if listener is not None:
            listener.close()
        for port in owned:
            port.close()
        stores.close()
    evidence["owned_cleanup"] = True
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
