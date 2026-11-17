# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual PostgreSQL migration and domain CAS without touching application storage."""

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeJobState, knowledge_job_id
from contracts.knowledge_cleanse import KnowledgeCleanseState, cleanse_job_id
from contracts.knowledge_ingestion import INGESTION_DATASET, KnowledgeIngestionIntent
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.storage.errors import Conflict
from nexent.storage.models import FieldPatch, OperationContext, Revision, StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_ingestion import bind_ingestion_records


def docker(*args, check=True):
    result = subprocess.run(
        ["docker", *args], text=True, capture_output=True, timeout=30, check=False
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip() if check else result.returncode


def context():
    return OperationContext("journal-proof-" + uuid4().hex, time.monotonic() + 10)


@pytest.mark.case_id("DPR-INGESTION-JOURNAL-D3-001")
@pytest.mark.stage("D3")
def test_persistent_ingestion_journal(record_property):
    run_id = uuid4().hex
    name = "nexent-ingestion-journal-" + run_id
    engine = None
    ports = []
    evidence = {}
    docker("image", "inspect", "postgres:15-alpine")
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "nexent.test_run=" + run_id,
            "-e",
            "POSTGRES_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::5432",
            "postgres:15-alpine",
        )
        deadline = time.monotonic() + 25
        while docker("exec", name, "pg_isready", "-U", "postgres", check=False):
            assert time.monotonic() < deadline, (
                "Owned PostgreSQL startup exceeded its deadline"
            )
            time.sleep(0.1)
        port = int(docker("port", name, "5432").splitlines()[0].rsplit(":", 1)[1])
        engine = sa.create_engine(
            sa.URL.create(
                "postgresql+psycopg2",
                username="postgres",
                password="fixture-password",
                host="127.0.0.1",
                port=port,
                database="postgres",
            ),
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
        original = KnowledgeFileLifecycle.__table__
        legacy = sa.Table(
            original.name,
            sa.MetaData(schema="nexent"),
            *[
                sa.Column(
                    column.name,
                    column.type,
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    server_default=column.server_default,
                )
                for column in original.c
                if column.name != "ingestion_request"
            ],
        )
        value = KnowledgeIngestionIntent(
            knowledge_id=1,
            file_id="b" * 32,
            file_version=0,
            user_id="user-a",
            attempt=1,
            source={
                "space": "files",
                "key": "source.txt",
                "version": "v1",
                "sha256": "a" * 64,
            },
            filename="source.txt",
            parser_version="parser-v1",
            embedding_model={"model_id": 2, "revision": "model-v1"},
            chunking_strategy="basic",
        )
        root = Path(__file__).resolve().parents[3]
        migration = (
            root / "deploy/sql/migrations/v2.9.0_019_knowledge_ingestion_intent.sql"
        )
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE SCHEMA nexent")
            legacy.create(conn)
            row = {
                "file_id": value.file_id,
                "tenant_id": "tenant-a",
                "knowledge_id": 1,
                "index_name": "kb-one",
                "original_filename": "source.txt",
                "source_generation": 0,
                "source_space": "files",
                "source_key": "source.txt",
                "source_revision": "v1",
                "source_sha256": "a" * 64,
                "status": "UPLOADED",
                "stage": "UPLOAD",
                "processing_attempt": 0,
                "version": 3,
                "delete_flag": "N",
            }
            conn.execute(
                legacy.insert(),
                [
                    row,
                    {**row, "file_id": "c" * 32},
                    {
                        **row,
                        "file_id": "d" * 32,
                        "original_filename": "legacy.txt",
                        "source_space": None,
                        "source_key": None,
                        "source_revision": None,
                        "source_sha256": None,
                        "status": "COMPLETED",
                        "stage": "COMPLETE",
                    },
                ],
            )
            for _ in range(2):
                conn.exec_driver_sql(migration.read_text(encoding="utf-8"))
            assert conn.execute(
                sa.text(
                    "SELECT data_type, is_nullable FROM information_schema.columns WHERE table_schema='nexent' AND table_name='knowledge_file_lifecycle_t' AND column_name='ingestion_request'"
                )
            ).one() == ("jsonb", "YES")
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT col_description('nexent.knowledge_file_lifecycle_t'::regclass, attnum) FROM pg_attribute WHERE attrelid='nexent.knowledge_file_lifecycle_t'::regclass AND attname='ingestion_request'"
                    )
                )
                == original.c.ingestion_request.comment
            )
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_indexes WHERE schemaname='nexent' AND indexname='idx_knowledge_ingestion_pending'"
                    )
                )
                == 1
            )
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM nexent.knowledge_file_lifecycle_t WHERE ingestion_request IS NULL"
                    )
                )
                == 3
            )
        evidence["migration"] = True
        scope = StorageScope("management", "tenant-a", "user-a", {INGESTION_DATASET})
        records = bind_ingestion_records(scope, engine)
        ports.append(records)
        journal = IngestionJournal(records)
        baseline = journal.record(value.file_id, context=context())
        barrier = Barrier(2)

        def admit():
            own = bind_ingestion_records(scope, engine)
            try:
                barrier.wait(timeout=5)
                try:
                    IngestionJournal(own).admit(value, baseline, context=context())
                    return "won"
                except Conflict:
                    return "conflict"
            finally:
                own.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(admit), pool.submit(admit)]
            assert sorted(future.result(timeout=15) for future in futures) == [
                "conflict",
                "won",
            ]
        accepted = journal.record(value.file_id, context=context())
        assert accepted["version"] == 4
        assert accepted["ingestion_request"] == value.model_dump(mode="json")
        assert journal.admit(value, accepted, context=context()) == accepted
        assert accepted["process_task_id"] == cleanse_job_id(
            value.cleanse_request(), "tenant-a", "user-a"
        )
        assert accepted["updated_by"] == "user-a" and accepted["update_time"]
        evidence["concurrent_admission"] = True
        reserved = journal.begin_cleanse(accepted, context=context())
        with pytest.raises(Conflict):
            journal.begin_cleanse(accepted, context=context())
        child = KnowledgeCleanseState(
            **value._reference(),
            job_id=reserved["process_task_id"],
            status="completed",
            artifact=value.source,
        )
        forwarding, payload = journal.begin_runtime(reserved, child, context=context())
        assert forwarding["forward_task_id"] == knowledge_job_id(
            payload, "tenant-a", "user-a"
        )
        assert (
            payload.embedding_model == value.embedding_model
            and payload.artifact == value.source
        )
        with pytest.raises(Conflict):
            journal.begin_runtime(reserved, child, context=context())
        final = journal.observe_runtime(
            forwarding,
            KnowledgeJobState(
                **value._reference(),
                job_id=forwarding["forward_task_id"],
                status="completed",
            ),
            context=context(),
        )
        assert final["status"] == "COMPLETED" and final["completed_at"]
        assert final["ingestion_request"] == accepted["ingestion_request"]
        evidence["fixed_child_phases"] = True
        foreign = bind_ingestion_records(
            StorageScope("management", "tenant-b", "foreign", {INGESTION_DATASET}),
            engine,
        )
        ports.append(foreign)
        assert foreign.get(INGESTION_DATASET, value.file_id, context=context()) is None
        assert not foreign.patch(
            INGESTION_DATASET,
            value.file_id,
            FieldPatch(set_values={"stage": "FOREIGN"}),
            expected=Revision(str(final["version"])),
            context=context(),
        ).matched
        stale = journal.record("c" * 32, context=context())
        second = journal.admit(
            value.model_copy(update={"file_id": "c" * 32}), stale, context=context()
        )
        records.patch(
            INGESTION_DATASET,
            "c" * 32,
            FieldPatch(set_values={"status": "DELETE_REQUESTED"}),
            expected=Revision(str(second["version"])),
            context=context(),
        )
        with pytest.raises(Conflict):
            journal.begin_cleanse(second, context=context())
        assert (
            journal.record("c" * 32, context=context())["status"] == "DELETE_REQUESTED"
        )
        for malformed in ([], {"oversized": "x" * 17000}):
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "UPDATE nexent.knowledge_file_lifecycle_t SET ingestion_request=CAST(:payload AS jsonb) WHERE file_id=:file_id"
                    ),
                    {"payload": json.dumps(malformed), "file_id": value.file_id},
                )
        assert journal.record(value.file_id, context=context())[
            "ingestion_request"
        ] == value.model_dump(mode="json")
        evidence["scope_and_constraints"] = True
        preserved = journal.record("d" * 32, context=context())
        assert (
            preserved["ingestion_request"] is None
            and preserved["original_filename"] == "legacy.txt"
        )
        assert (
            preserved["source_revision"] is None and preserved["status"] == "COMPLETED"
        )
    finally:
        for records in ports:
            records.close()
        if engine is not None:
            engine.dispose()
        for container in docker(
            "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id
        ).splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
        evidence["owned_cleanup"] = True
    assert all(
        evidence.get(key) is True
        for key in (
            "migration",
            "concurrent_admission",
            "fixed_child_phases",
            "scope_and_constraints",
            "owned_cleanup",
        )
    )
    record_property("ingestion_journal_probe", json.dumps(evidence, sort_keys=True))
