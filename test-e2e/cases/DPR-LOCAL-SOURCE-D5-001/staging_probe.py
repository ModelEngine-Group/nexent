# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the shipped staging schema and production scoped ports on owned PostgreSQL."""

import pytest
import sqlalchemy as sa
from management.services.file.local_source_staging import LocalSourceStaging
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, NotFound

from infrastructure.knowledge_ingestion import knowledge_ingestion_ports
from infrastructure.local_source_staging import local_source_staging_port
from infrastructure.rdb.local_source_staging import KnowledgeLocalSource


def prove_staging(engine, root, context):
    migration = (
        root / "deploy/sql/migrations/v2.9.0_021_local_source_staging.sql"
    ).read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(migration)
        connection.exec_driver_sql(migration)
        columns = sa.inspect(connection).get_columns(
            "knowledge_local_source_t", schema="nexent"
        )
        assert all(column["comment"] for column in columns)
        indexes = sa.inspect(connection).get_indexes(
            "knowledge_local_source_t", schema="nexent"
        )
        assert any(
            i["name"] == "idx_local_source_owner_path" and not i["unique"]
            for i in indexes
        )
    with local_source_staging_port("tenant-a", "user-a", context=context()) as records:
        journal = LocalSourceStaging(records)
        row = journal.reserve(
            "a" * 32,
            "/owned/staged/source.txt",
            "source.txt",
            4,
            "e" * 64,
            context=context(),
        )
        ready = journal.confirm(row, context=context())
        with knowledge_ingestion_ports("tenant-a", "user-a", context=context()) as (
            _,
            resources,
        ):
            authorization = KnowledgeFileAuthorization(resources, user_id="user-a")
            binding = journal.bind(ready, 1, "f" * 32, authorization, context=context())
            with pytest.raises(Conflict):
                journal.bind(ready, 1, "c" * 32, authorization, context=context())
        done = journal.complete(binding, context=context())
        assert done["state"] == "BOUND" and done["bound_file_id"] == "f" * 32
        assert done["source_sha256"] == "e" * 64 and done["created_by"] == "user-a"
    for tenant, user in (("tenant-b", "user-a"), ("tenant-a", "user-b")):
        with (
            local_source_staging_port(tenant, user, context=context()) as records,
            pytest.raises(NotFound),
        ):
            LocalSourceStaging(records).find(
                row["local_source_path"], context=context()
            )
    table = KnowledgeLocalSource.__table__
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(table.update().values(file_size=-1))
    with engine.connect() as connection:
        actual = connection.execute(sa.select(table)).mappings().one()
        assert actual["state"] == "BOUND" and actual["file_size"] == 4
