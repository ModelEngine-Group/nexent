# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real resource records, tenant-scoped catalogs and Management DAC authorization."""

from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.cleanse_jobs import CleanseJobs
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.account_record import (
    TenantGroupInfo,
    TenantGroupUser,
    UserAccount,
    UserTenant,
)
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord


def check_resources(engine, source, records, context):
    tables = [
        UserTenant.__table__,
        TenantGroupInfo.__table__,
        TenantGroupUser.__table__,
        UserAccount.__table__,
        KnowledgeRecord.__table__,
        KnowledgeFileLifecycle.__table__,
    ]
    with engine.begin() as conn:
        for table in tables:
            table.create(conn, checkfirst=True)
        conn.execute(
            UserTenant.__table__.insert().values(
                user_tenant_id=1,
                user_id="user-a",
                tenant_id="tenant-a",
                delete_flag="N",
            )
        )
        conn.execute(
            UserAccount.__table__.insert().values(
                account_id=1, user_id="user-a", user_roles=["DEV"], delete_flag="N"
            )
        )
        conn.execute(
            KnowledgeRecord.__table__.insert().values(
                knowledge_id=1,
                index_name="kb-one",
                tenant_id="tenant-a",
                created_by="user-a",
                delete_flag="N",
            )
        )
        conn.execute(
            KnowledgeFileLifecycle.__table__.insert().values(
                file_id="b" * 32,
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
        StorageScope("management", "tenant-a", "worker", set(TABLES)), engine
    )
    authorization = KnowledgeCleanseAuthorization(resources, user_id="user-a")
    request = KnowledgeCleanseRequest(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        source=source,
        filename="source.txt",
        idempotency_key="authorized",
    )
    jobs = CleanseJobs(
        records, authorize=authorization.authorize, parser_version="parser-v1"
    )
    state = jobs.submit(request, context=context())
    handle = jobs.claim(
        "authorized-worker", job_id=state.job_id, lease_seconds=60, context=context()
    )
    assert (
        authorization.authorize_execution(handle, request, context=context()) == source
    )
    with engine.begin() as conn:
        conn.execute(UserAccount.__table__.update().values(user_roles=[]))
    try:
        authorization.authorize_execution(handle, request, context=context())
    except ScopeDenied:
        pass
    else:
        raise AssertionError("revoked account role retained cleansing permission")
    with engine.begin() as conn:
        conn.execute(UserAccount.__table__.update().values(user_roles=["DEV"]))
        conn.execute(
            KnowledgeFileLifecycle.__table__.update().values(source_generation=1)
        )
    try:
        authorization.authorize(request, context=context())
    except ScopeDenied:
        pass
    else:
        raise AssertionError("stale source generation was authorized")
    # Retire this fixture job so it does not enter subsequent scheduling assertions.
    assert jobs.transition(
        handle, status="failed", error_code="FIXTURE_REVOKED", context=context()
    )
    resources.close()
