# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual Runtime KB transactions with owned PostgreSQL and controlled race timing."""

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-KB-D3-001")
def test_durable_knowledge_visibility(record_property, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]
    import sqlalchemy as sa
    from contracts.agentos_knowledge import (
        KnowledgeFileDelete,
        KnowledgeFileUpload,
        KnowledgeJobLookup,
    )
    from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
    from nexent.storage.errors import Conflict, NotFound
    from nexent.storage.models import OperationContext, RecordQuery, StorageScope
    from runtime.knowledge_base.jobs import KnowledgeJobs

    from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs
    from infrastructure.rdb.record_store import SQLRecordStore

    def docker(*args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=30
        ).strip()

    def context():
        return OperationContext("kb-probe-" + uuid4().hex, time.monotonic() + 20)

    def lookup(state):
        return KnowledgeJobLookup(
            **state.model_dump(
                include={"knowledge_id", "file_id", "file_version", "job_id"}
            )
        )

    def deletion(request, key):
        return KnowledgeFileDelete(
            **request.model_dump(include={"knowledge_id", "file_id", "file_version"}),
            idempotency_key=key,
        )

    name = "dpr-kb-" + uuid4().hex
    container = engine = None
    ports = []
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
                timeout=10,
                check=False,
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
            connect_args={"connect_timeout": 2, "options": "-c timezone=Asia/Shanghai"},
            hide_parameters=True,
        )
        migration = root / "deploy/sql/migrations/v2.9.0_017_runtime_knowledge_jobs.sql"
        with engine.begin() as connection:
            assert (
                connection.exec_driver_sql("SHOW TIME ZONE").scalar_one()
                == "Asia/Shanghai"
            )
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
        inspector = sa.inspect(engine)
        for table in ("runtime_knowledge_file_t", "runtime_knowledge_job_t"):
            assert inspector.get_table_comment(table, schema="nexent")["text"]
            assert all(
                column["comment"]
                for column in inspector.get_columns(table, schema="nexent")
            )
            assert not inspector.get_foreign_keys(table, schema="nexent")
            assert not inspector.get_unique_constraints(table, schema="nexent")
            assert all(
                not index["unique"]
                for index in inspector.get_indexes(table, schema="nexent")
            )
        now = [datetime.now(timezone.utc)]

        def service(tenant="tenant-a", user="user-a"):
            records = bind_knowledge_jobs(
                StorageScope("runtime", tenant, user, {FILES, JOBS}), engine
            )
            ports.append(records)
            return KnowledgeJobs(
                records, authorize=lambda request, **kw: None, clock=lambda: now[0]
            )

        owner = service()
        payload = KnowledgeFileUpload(
            knowledge_id=1,
            file_id="a" * 32,
            file_version=1,
            idempotency_key="upload",
            parser_version="v2",
            artifact={
                "space": "files",
                "key": "artifact",
                "version": "v1",
                "sha256": "a" * 64,
            },
            embedding_model={"model_id": 2, "revision": "model-v1"},
        )
        before = datetime.now(timezone.utc) - timedelta(seconds=2)
        admitted = owner.submit(payload, context=context())
        assert owner.submit(payload, context=context()) == admitted
        with pytest.raises(Conflict):
            owner.submit(
                payload.model_copy(update={"parser_version": "changed"}),
                context=context(),
            )
        for other in (service(user="other"), service(tenant="other")):
            with pytest.raises(NotFound):
                other.inspect(lookup(admitted), context=context())
        persisted = owner.records.get(JOBS, admitted.job_id, context=context())
        assert (
            before
            <= datetime.fromisoformat(persisted["create_time"])
            <= datetime.now(timezone.utc) + timedelta(seconds=2)
        )

        barrier = Barrier(2)
        original = SQLRecordStore.patch

        def synchronized(store, dataset, key, patch, **kwargs):
            if dataset == FILES and not patch.set_values:
                barrier.wait(timeout=5)
            return original(store, dataset, key, patch, **kwargs)

        async def race():
            manager = ThreadManager(
                service_name="runtime-kb-race",
                lane_policies={
                    "control-io": LanePolicy(
                        name="control-io",
                        max_workers=2,
                        max_queue_size=2,
                        queue_timeout_seconds=0,
                        cancel_grace_seconds=2,
                        shutdown_grace_seconds=5,
                    ),
                },
            )
            manager.start()
            try:
                requests = [
                    payload.model_copy(
                        update={"file_version": 2, "idempotency_key": key}
                    )
                    for key in ("race-a", "race-b")
                ]
                return await asyncio.gather(
                    *(
                        manager.run(
                            "control-io",
                            ManagedTaskSpec(
                                task_name="kb-admission", owner="runtime-kb-proof"
                            ),
                            service().submit,
                            request,
                            context=context(),
                        )
                        for request in requests
                    ),
                    return_exceptions=True,
                )
            finally:
                drained = await manager.shutdown(timeout=5)
                assert not drained.stuck_execution_ids

        monkeypatch.setattr(SQLRecordStore, "patch", synchronized)
        try:
            results = asyncio.run(race())
        finally:
            monkeypatch.setattr(SQLRecordStore, "patch", original)
        assert sum(isinstance(item, Conflict) for item in results) == 1, [
            type(item).__name__ for item in results
        ]
        assert owner.records.count(JOBS, RecordQuery(), context=context()) == 2
        winner = next(item for item in results if not isinstance(item, Exception))
        handle = owner.claim(
            lookup(winner), owner_id="instance-a", lease_seconds=30, context=context()
        )
        assert owner.begin_execution(handle, context=context())
        assert owner.complete(handle, chunk_count=2, context=context())
        completed_row = owner.records.get(JOBS, winner.job_id, context=context())
        for field in ("create_time", "update_time"):
            assert (
                before
                <= datetime.fromisoformat(completed_row[field])
                <= datetime.now(timezone.utc) + timedelta(seconds=2)
            )
        assert completed_row["created_by"] == completed_row["updated_by"] == "user-a"
        assert owner.is_visible(lookup(winner), handle["attempt_id"], context=context())
        deleted = owner.submit(
            deletion(lookup(winner), "delete-visible"), context=context()
        )
        assert not owner.is_visible(
            lookup(winner), handle["attempt_id"], context=context()
        )
        assert not owner.complete(handle, chunk_count=2, context=context())
        assert owner.finish_delete(
            owner.begin_delete(lookup(deleted), owner_id="cleaner", context=context()),
            physical_absence_confirmed=True, context=context()
        ).physical_cleanup_complete

        other_file = payload.model_copy(update={"file_id": "b" * 32})
        state = owner.submit(other_file, context=context())
        active = owner.claim(
            lookup(state), owner_id="old", lease_seconds=10, context=context()
        )
        assert owner.begin_execution(active, context=context())
        now[0] += timedelta(seconds=11)
        assert (
            owner.claim(
                lookup(state),
                owner_id="replacement",
                lease_seconds=10,
                context=context(),
            )
            is None
        )
        deleting = owner.submit(
            deletion(other_file, "delete-running"), context=context()
        )
        assert not owner.cleanup_ready(lookup(deleting), context=context())
        assert owner.begin_delete(lookup(deleting), owner_id="blocked-cleaner", context=context()) is None
        with pytest.raises(Conflict):
            owner.finish_delete(
                lookup(deleting), physical_absence_confirmed=True, context=context()
            )
        assert owner.end_attempt(active, writer_ended=True, context=context())
        assert owner.cleanup_ready(lookup(deleting), context=context())
        final = owner.finish_delete(
            owner.begin_delete(lookup(deleting), owner_id="cleaner", context=context()),
            physical_absence_confirmed=True, context=context()
        )
        assert final.status == "deleted" and final.physical_cleanup_complete
        with pytest.raises(Conflict):
            owner.submit(
                other_file.model_copy(update={"idempotency_key": "late-upload"}),
                context=context(),
            )
        record_property(
            "knowledge_probe",
            json.dumps(
                {
                    "migration_idempotent": True,
                    "concurrent_cas": True,
                    "writer_fencing": True,
                    "logical_deletion": True,
                    "physical_absence_controlled": True,
                    "utc_audit": True,
                    "dependency_image_id": image_id,
                    "source_hashes": {
                        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                        for path in (
                            "backend/runtime/knowledge_base/jobs.py",
                            "infrastructure/rdb/knowledge_jobs.py",
                            "deploy/sql/migrations/v2.9.0_017_runtime_knowledge_jobs.sql",
                        )
                    },
                },
                sort_keys=True,
            ),
        )
    finally:
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
