# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Disposable PostgreSQL/Redis integration; parser output is a controlled fixture."""

import hashlib
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]
import sqlalchemy as sa
from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from contracts.knowledge_cleanse import KnowledgeCleanseLookup, KnowledgeCleanseRequest
from management.services.file.cleanse_consumer import serve
from management.services.file.cleanse_jobs import CleanseJobs
from management.services.file.cleanse_lease import CleanseLeaseGuard
from management.services.file.cleanse_worker import (
    HANDLER,
    CleanseHandler,
    HandlerRegistry,
    consume_once,
    enqueue_ready,
)
from nexent.storage.errors import NotFound, OperationCancelled, ScopeDenied
from nexent.storage.models import (
    Comparison,
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
)
from resource_probe import check_resources
from source_probe import check_source_publication
from upload_records_probe import check_upload_transactions

from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
from infrastructure.redis.kv import RedisKeyValueConfig, RedisKeyValueStore
from infrastructure.storage.work_queue import KombuWorkQueue, QueueBinding


def diagnostic_exception(kind, error, trace):
    """Retain safe cause types/locations even when storage intentionally hides details."""
    cause, seen = error, set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        locations = [
            (frame.name, frame.lineno)
            for frame in traceback.extract_tb(cause.__traceback__)
        ]
        print(
            "probe_failure_cause",
            type(cause).__module__,
            type(cause).__name__,
            getattr(cause, "errno", None),
            getattr(cause, "winerror", None),
            locations[-4:],
            file=sys.stderr,
        )
        cause = cause.__context__
    sys.__excepthook__(kind, error, trace)


sys.excepthook = diagnostic_exception


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=40
    ).strip()


def context():
    return OperationContext("cleanse-job-probe", time.monotonic() + 10)


def published():
    return ObjectReference(
        space="files",
        key="fixture/artifact.json",
        version="etag:fixture",
        sha256="2" * 64,
    )


run_id = sys.argv[1]
assert len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)
containers = []
engine = queue = kv = None
try:
    pg = docker(
        "run",
        "--rm",
        "-d",
        "--label",
        f"nexent.test_run={run_id}",
        "-e",
        "POSTGRES_PASSWORD=fixture-password",
        "-p",
        "127.0.0.1::5432",
        "postgres:15-alpine",
    )
    containers.append(pg)
    redis = docker(
        "run",
        "--rm",
        "-d",
        "--label",
        f"nexent.test_run={run_id}",
        "-p",
        "127.0.0.1::6379",
        "redis:7-alpine",
    )
    containers.append(redis)
    minio = docker(
        "run",
        "--rm",
        "-d",
        "--label",
        f"nexent.test_run={run_id}",
        "-e",
        "MINIO_ROOT_USER=fixture-user",
        "-e",
        "MINIO_ROOT_PASSWORD=fixture-password",
        "-p",
        "127.0.0.1::9000",
        "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z",
        "server",
        "/data",
    )
    containers.append(minio)

    def port(container, key):
        return json.loads(
            docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", container)
        )[key][0]["HostPort"]

    engine = sa.create_engine(
        f"postgresql+psycopg2://postgres:fixture-password@127.0.0.1:{port(pg, '5432/tcp')}/postgres",
        connect_args={"connect_timeout": 1, "options": "-c timezone=Asia/Shanghai"},
        hide_parameters=True,
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            break
        except sa.exc.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA nexent")
        cleanse_jobs.create(conn, checkfirst=True)

    def service(user="user-a", tenant="tenant-a"):
        records = bind_cleanse_jobs(
            StorageScope("management", tenant, user, {DATASET}), engine
        )
        return CleanseJobs(
            records,
            authorize=lambda request, **kwargs: None,
            parser_version="parser-v1",
        )

    public = service()
    worker = service("worker")
    request = FileCleanseRequest(
        run_id="a" * 32,
        source=ObjectReference(
            space="files", key="source.txt", version="etag:s", sha256="1" * 64
        ),
        filename="source.txt",
        idempotency_key="first",
    )
    admission_before = datetime.now(timezone.utc)
    state = public.submit(request, context=context())
    admission_after = datetime.now(timezone.utc)
    assert public.submit(request, context=context()).job_id == state.job_id
    lookup = FileCleanseLookup(run_id=state.run_id, job_id=state.job_id)
    for foreign in (service("user-b"), service(tenant="tenant-b")):
        try:
            foreign.inspect(lookup, context=context())
        except NotFound:
            pass
        else:
            raise AssertionError("foreign job leaked")
    scope = StorageScope("management", "tenant-a", "worker", {"cleanse"})
    url = f"redis://127.0.0.1:{port(redis, '6379/tcp')}/0"
    kv = RedisKeyValueStore(
        RedisKeyValueConfig(url, "probe"), scope, namespace="cleanse"
    )
    queue = KombuWorkQueue(
        scope, QueueBinding("cleanse", url, {"management"}, {HANDLER}), kv
    )
    executions = []

    def execute(row, request, **kwargs):
        assert row["user_id"] == "user-a"
        executions.append(row["job_id"])
        return published()

    handler = CleanseHandler(
        worker,
        owner_id="worker-1",
        lease_seconds=60,
        authorize_execution=lambda row, request, **kwargs: None,
        execute=execute,
    )
    registry = HandlerRegistry({HANDLER: handler})
    assert enqueue_ready(worker, queue, context=context()) == 1
    assert enqueue_ready(worker, queue, context=context()) == 1
    for _ in range(2):
        assert consume_once(queue, registry, max_wait=0.5, context=context())
    assert len(executions) == 1
    assert public.inspect(lookup, context=context()).artifact == published()
    kb_request = KnowledgeCleanseRequest(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        **request.model_dump(exclude={"run_id"}),
    )
    kb = public.submit(kb_request, context=context())
    kb_lookup = KnowledgeCleanseLookup(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        job_id=kb.job_id,
    )
    assert "run_id" not in kb.model_dump()
    assert public.submit(kb_request, context=context()).job_id == kb.job_id
    assert kb.job_id != state.job_id
    for foreign, query in (
        (service("user-b"), kb_lookup),
        (service(tenant="tenant-b"), kb_lookup),
        (public, kb_lookup.model_copy(update={"knowledge_id": 2})),
        (public, kb_lookup.model_copy(update={"file_id": "c" * 32})),
        (public, kb_lookup.model_copy(update={"file_version": 1})),
    ):
        for method in (foreign.inspect, foreign.cancel):
            try:
                method(query, context=context())
            except NotFound:
                pass
            else:
                raise AssertionError("foreign knowledge context leaked or cancelled")
    assert enqueue_ready(worker, queue, context=context()) == 1
    assert enqueue_ready(worker, queue, context=context()) == 1
    for _ in range(2):
        assert consume_once(queue, registry, max_wait=0.5, context=context())
    assert executions.count(kb.job_id) == 1
    assert public.inspect(kb_lookup, context=context()).artifact == published()
    req2 = request.model_copy(update={"idempotency_key": "stale"})
    second = public.submit(req2, context=context())
    clock = [datetime.now(timezone.utc)]
    worker.clock = lambda: clock[0]
    old = worker.claim("old", job_id=second.job_id, lease_seconds=1, context=context())
    clock[0] += timedelta(seconds=2)
    new = worker.claim("new", job_id=second.job_id, lease_seconds=60, context=context())
    assert new and not worker.transition(
        old, status="completed", artifact=published(), context=context()
    )
    assert worker.transition(
        new, status="completed", artifact=published(), context=context()
    )
    renewal = public.submit(
        request.model_copy(update={"idempotency_key": "lease-guard"}), context=context()
    )
    renewal_handle = worker.claim(
        "guarded", job_id=renewal.job_id, lease_seconds=60, context=context()
    )
    tick_clock, authorization_checks = [0], []
    guard = CleanseLeaseGuard(
        worker,
        lease_seconds=60,
        clock=lambda: tick_clock[0],
        authorize_execution=lambda row, request, **kwargs: authorization_checks.append(
            row["user_id"]
        ),
    )
    clock[0] += timedelta(seconds=30)
    guard(renewal_handle, context=context())
    clock[0] += timedelta(seconds=31)
    assert (
        worker.claim(
            "intruder", job_id=renewal.job_id, lease_seconds=60, context=context()
        )
        is None
    )
    assert authorization_checks == ["user-a"]
    public.cancel(
        FileCleanseLookup(run_id=request.run_id, job_id=renewal.job_id),
        context=context(),
    )
    tick_clock[0] = 21
    try:
        guard(renewal_handle, context=context())
    except OperationCancelled:
        pass
    else:
        raise AssertionError("cancelled lease was renewed")
    unknown = public.submit(
        request.model_copy(update={"idempotency_key": "unknown"}), context=context()
    )
    handle = worker.claim(
        "uncertain", job_id=unknown.job_id, lease_seconds=60, context=context()
    )
    assert worker.mark_uncertain(handle, context=context())
    clock[0] += timedelta(seconds=120)
    assert worker.ready(context=context()) == ()
    check_resources(engine, request.source, public.records, context)
    check_source_publication(engine, port(minio, "9000/tcp"), context, queue, url)
    last = public.submit(
        request.model_copy(update={"idempotency_key": "consumer-stop"}),
        context=context(),
    )
    assert enqueue_ready(worker, queue, context=context()) == 1
    stop = Event()

    def finish_and_stop(task, *, context):
        handler(task, context=context)
        stop.set()

    serve(
        queue,
        HandlerRegistry({HANDLER: finish_and_stop}),
        stop=stop,
        operation_seconds=10,
    )
    assert (
        public.inspect(
            FileCleanseLookup(run_id=request.run_id, job_id=last.job_id),
            context=context(),
        ).status
        == "completed"
    )
    try:
        enqueue_ready(worker, queue, context=context())
        queue.consume(max_wait=0.1, context=context())
    except ScopeDenied:
        pass
    else:
        raise AssertionError("stopped consumer did not close the queue")
    row = public.records.query(
        DATASET,
        RecordQuery(where=Comparison("job_id", "eq", state.job_id)),
        PageRequest(),
        context=context(),
    ).items[0]
    assert (
        admission_before
        <= datetime.fromisoformat(row["create_time"])
        <= admission_after
    )
    dated = public.records.query(
        DATASET,
        RecordQuery(where=Comparison("create_time", "gte", row["create_time"])),
        PageRequest(),
        context=context(),
    ).items
    assert any(item["job_id"] == state.job_id for item in dated)
    with engine.connect() as conn:
        comments = conn.execute(
            sa.text(
                "SELECT count(*) FROM pg_description d JOIN pg_class c ON c.oid=d.objoid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='nexent' AND c.relname='file_cleanse_job_t' AND d.objsubid>0"
            )
        ).scalar_one()
    assert comments == len(cleanse_jobs.columns)
    check_upload_transactions(engine, context)
    result = {
        "column_comments": comments,
        "admission_replay": True,
        "ownership": True,
        "redis_dispatch": True,
        "duplicate_executes_once": True,
        "lease_takeover_fenced": True,
        "unknown_outcome_quarantined": True,
        "utc_audit_with_non_utc_session": True,
        "knowledge_scope_ownership": True,
        "knowledge_dispatch": True,
        "consumer_stopped_closed": True,
        "lease_guard_renewal_and_cancel": True,
        "live_resource_authorization": True,
        "source_publication_and_reconciliation": True,
        "automatic_source_identity_reconciliation": True,
        "source_ledger_atomic_domain": True,
        "recovery_accounting_and_quota": True,
        "ledger_access_snapshot_and_release": True,
        "knowledge_worker_and_partitioned_artifact": True,
        "dispatch_root_stop_and_crash_fence": True,
        "source_publication_hashes": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in (
                "backend/management/services/file/cleanse_root.py",
                "backend/management/services/file/cleanse_jobs.py",
                "backend/management/services/file/cleanse_worker.py",
                "infrastructure/rdb/cleanse_dispatch.py",
                "infrastructure/knowledge_cleanse.py",
                "backend/management/services/file/knowledge_cleanse_worker.py",
                "infrastructure/file_processing/objects.py",
                "backend/management/services/file/knowledge_cleanse_service.py",
                "infrastructure/knowledge_cleanse.py",
                "backend/management/services/file/source_publish.py",
                "backend/management/services/file/source_reconcile.py",
                "backend/management/services/file/source_recovery.py",
                "backend/management/services/file/source_finalize.py",
                "backend/management/services/knowledge_base/usage_cache.py",
                "backend/management/services/file/source_upload.py",
                "backend/management/services/file/service.py",
                "infrastructure/source_upload.py",
                "infrastructure/rdb/source_binding.py",
                "infrastructure/rdb/source_candidates.py",
                "infrastructure/rdb/upload_records.py",
                "infrastructure/rdb/knowledge_storage_record.py",
                "infrastructure/rdb/record_queries.py",
                "infrastructure/rdb/composition.py",
                "infrastructure/rdb/storage_ledger.py",
                "infrastructure/storage_ledger.py",
                "backend/management/db/knowledge_base/storage_object.py",
                "sdk/nexent/storage/interfaces.py",
                "infrastructure/object_storage/composition.py",
            )
        },
    }
    print(json.dumps(result))
finally:
    if queue:
        queue.close()
    if kv:
        kv.close()
    if engine is not None:
        engine.dispose()
    for container in reversed(containers):
        docker("rm", "-f", "-v", container)
