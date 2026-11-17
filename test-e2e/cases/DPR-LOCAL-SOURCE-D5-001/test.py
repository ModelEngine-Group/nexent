# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual local-alias migration and production scoped registration against owned PostgreSQL."""

import hashlib
import io
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.case_id("DPR-LOCAL-SOURCE-D5-001")
@pytest.mark.stage("D5")
def test_local_source_alias_deployment(monkeypatch, tmp_path, record_property):
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [
        str(Path(__file__).parent),
        str(root),
        str(root / "backend"),
        str(root / "sdk"),
    ]
    import sqlalchemy as sa
    from contracts.constants import environment
    from contracts.knowledge_ingestion import INGESTION_DATASET
    from management.services.file.local_knowledge_source import publish_local_source
    from management.services.knowledge_base.ingestion_selection import (
        resolve_ingestion_file,
    )
    from nexent.storage.models import OperationContext, StorageScope

    from infrastructure.agentos_identity import ServicePrincipal
    from infrastructure.knowledge_ingestion import knowledge_ingestion_ports
    from infrastructure.rdb.account_record import (
        TenantGroupInfo,
        TenantGroupUser,
        UserAccount,
        UserTenant,
    )
    from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
    from infrastructure.rdb.knowledge_ingestion import bind_ingestion_records
    from infrastructure.rdb.knowledge_search_records import KnowledgeRecord

    name, engine = "nexent-local-alias-" + uuid4().hex, None

    def docker(*args, check=True):
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=30, check=check
        )
        return result.stdout.strip() if check else result.returncode

    def context():
        return OperationContext("local-alias-" + uuid4().hex, time.monotonic() + 10)

    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "nexent.test_run=" + name,
            "-e",
            "POSTGRES_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::5432",
            "postgres:15-alpine",
        )
        deadline = time.monotonic() + 25
        while docker("exec", name, "pg_isready", "-U", "postgres", check=False):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        port = docker("port", name, "5432").splitlines()[0].rsplit(":", 1)[1]
        for key, value in {
            "POSTGRES_USER": "postgres",
            "NEXENT_POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": port,
            "POSTGRES_DB": "postgres",
        }.items():
            monkeypatch.setattr(environment, key, value)
        engine = sa.create_engine(
            sa.URL.create(
                "postgresql+psycopg2",
                username="postgres",
                password="fixture-password",
                host="127.0.0.1",
                port=int(port),
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
                if column.name != "local_source_path"
            ],
        )
        data, file_id = b"local source alias", "b" * 32
        source = {
            "source_space": "files",
            "source_key": "knowledge/source.txt",
            "source_revision": "v1",
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_generation": 0,
        }
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA nexent")
            legacy.create(connection)
            connection.execute(
                legacy.insert().values(
                    file_id="d" * 32,
                    tenant_id="tenant-a",
                    knowledge_id=1,
                    index_name="kb-one",
                    original_filename="legacy.txt",
                    status="COMPLETED",
                    stage="COMPLETE",
                    delete_flag="N",
                )
            )
            migration = (
                root
                / "deploy/sql/migrations/v2.9.0_020_knowledge_local_source_alias.sql"
            ).read_text(encoding="utf-8")
            connection.exec_driver_sql(migration)
            connection.exec_driver_sql(migration)
            for table in (
                UserAccount.__table__,
                UserTenant.__table__,
                TenantGroupInfo.__table__,
                TenantGroupUser.__table__,
                KnowledgeRecord.__table__,
            ):
                table.create(connection)
            connection.execute(
                UserAccount.__table__.insert().values(
                    account_id=1, user_id="user-a", user_roles=["DEV"], delete_flag="N"
                )
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
                KnowledgeRecord.__table__.insert().values(
                    knowledge_id=1,
                    tenant_id="tenant-a",
                    index_name="kb-one",
                    created_by="user-a",
                    delete_flag="N",
                )
            )
            connection.execute(
                original.insert().values(
                    file_id=file_id,
                    tenant_id="tenant-a",
                    knowledge_id=1,
                    index_name="kb-one",
                    original_filename="source.txt",
                    file_size=len(data),
                    status="UPLOADED",
                    stage="UPLOAD",
                    created_by="user-a",
                    delete_flag="N",
                    **source,
                )
            )
            assert (
                connection.execute(
                    sa.select(original.c.local_source_path).where(
                        original.c.file_id == "d" * 32
                    )
                ).scalar_one()
                is None
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT col_description('nexent.knowledge_file_lifecycle_t'::regclass, attnum) FROM pg_attribute WHERE attrelid='nexent.knowledge_file_lifecycle_t'::regclass AND attname='local_source_path'"
                ).scalar_one()
                == "Management-owned local upload alias; never forwarded to Runtime."
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='nexent' AND indexname='idx_knowledge_file_local_source'"
                ).scalar_one()
                == 1
            )
        from staging_probe import prove_staging

        prove_staging(engine, root, context)
        record_property("local_staging_migration_and_actor_binding", "passed")
        actor = ServicePrincipal("user-a", "tenant-a")
        with knowledge_ingestion_ports(
            actor.tenant_id, actor.user_id, context=context()
        ) as (records, _):
            record = records.get(INGESTION_DATASET, file_id, context=context())
        row = publish_local_source(record, io.BytesIO(data), actor, tmp_path, context())
        assert Path(row["local_source_path"]).read_bytes() == data
        assert all(row[key] == value for key, value in source.items())
        with knowledge_ingestion_ports(
            actor.tenant_id, actor.user_id, context=context()
        ) as (_, resources):
            selected = resolve_ingestion_file(
                resources,
                actor,
                "kb-one",
                {"path_or_url": row["local_source_path"]},
                destination="local",
                context=context(),
            )
            assert selected["file_id"] == file_id
        foreign = bind_ingestion_records(
            StorageScope("management", "other", "user-a", {INGESTION_DATASET}), engine
        )
        try:
            assert foreign.get(INGESTION_DATASET, file_id, context=context()) is None
        finally:
            foreign.close()
        with pytest.raises(sa.exc.DataError), engine.begin() as connection:
            connection.execute(
                original.update()
                .where(original.c.file_id == file_id)
                .values(local_source_path="x" * 2049)
            )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(original.c.local_source_path).where(
                        original.c.file_id == file_id
                    )
                ).scalar_one()
                == row["local_source_path"]
            )
        record_property("local_alias_migration_and_scoped_publication", "passed")
    finally:
        if engine is not None:
            engine.dispose()
        if docker("ps", "-aq", "--filter", "name=^/" + name + "$"):
            docker("rm", "-f", "-v", name)
        assert not docker("ps", "-aq", "--filter", "name=^/" + name + "$")
