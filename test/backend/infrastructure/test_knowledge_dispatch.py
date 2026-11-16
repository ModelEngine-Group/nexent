# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only Runtime discovery omits payloads and excludes previously begun attempts."""

from datetime import timedelta

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, StorageScope
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.rdb.knowledge_dispatch import DATASET, bind_knowledge_dispatch
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs
from test.backend.services.test_knowledge_jobs import (
    lookup,
)
from test.backend.services.test_knowledge_jobs import (
    setup as setup,  # noqa: PLC0414 - Pytest fixture re-export.
)


def test_discovery_is_metadata_only_and_read_only(setup):
    policy, _, engine, request, context, _, _ = setup
    state = policy.submit(request, context=context)
    other = bind_knowledge_jobs(StorageScope("runtime", "other", "other-user", {FILES, JOBS}), engine)
    discover = bind_knowledge_dispatch(engine)
    try:
        other_state = KnowledgeJobs(other, authorize=lambda *a, **kw: None).submit(request, context=context)
        page = discover.query(DATASET, RecordQuery(), PageRequest(limit=100), context=context)
        assert {r["job_id"] for r in page.items} == {state.job_id, other_state.job_id}
        assert {r["tenant_id"] for r in page.items} == {"tenant", "other"}
        assert {r["user_id"] for r in page.items} == {"user", "other-user"}
        assert all("request_payload" not in r and "request_hash" not in r for r in page.items)
        with pytest.raises(ScopeDenied):
            discover.create(DATASET, {}, context=context)
        with pytest.raises(InvalidInput):
            discover.query(DATASET, RecordQuery(fields=("request_payload",)), PageRequest(), context=context)
    finally:
        other.close()
        discover.close()


def test_running_started_failed_or_soft_deleted_are_not_discovered(setup):
    policy, _records, engine, request, context, now, _ = setup
    state = policy.submit(request, context=context)
    discover = bind_knowledge_dispatch(engine)
    try:
        handle = policy.claim(lookup(state), owner_id="owner", lease_seconds=1, context=context)
        now[0] += timedelta(seconds=2)
        assert not discover.query(DATASET, RecordQuery(), PageRequest(), context=context).items
        # An expired attempt remains excluded; discovery never automatically replays it.
        handle = policy.claim(lookup(state), owner_id="owner2", lease_seconds=5, context=context)
        assert policy.begin_execution(handle, context=context)
        policy.end_attempt(handle, writer_ended=False, context=context)
        assert not discover.query(DATASET, RecordQuery(), PageRequest(), context=context).items
        fresh = policy.submit(request.model_copy(update={"file_id": "b" * 32}), context=context)
        from infrastructure.rdb.knowledge_jobs import jobs
        with engine.begin() as connection:
            connection.execute(jobs.update().where(jobs.c.job_id == fresh.job_id).values(delete_flag="Y"))
        assert not discover.query(DATASET, RecordQuery(), PageRequest(), context=context).items
    finally:
        discover.close()
