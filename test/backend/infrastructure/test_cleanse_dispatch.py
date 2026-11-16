# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Discovery reveals known cleansing scopes without exposing payload or writes."""

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery

from infrastructure.rdb.cleanse_dispatch import DATASET, bind_cleanse_dispatch
from test.backend.services.test_cleanse_jobs import context, request
from test.backend.services.test_cleanse_jobs import setup as setup  # noqa: PLC0414
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


def test_discovery_includes_known_scopes_but_excludes_unknown_work_and_hides_payload(setup):
    make, _ = setup
    jobs = make()
    ready = jobs.submit(knowledge_request(), context=context())
    run = jobs.submit(request(), context=context())
    uncertain = jobs.submit(
        knowledge_request().model_copy(update={"idempotency_key": "unknown"}),
        context=context(),
    )
    attempt = jobs.claim(
        "worker", job_id=uncertain.job_id, lease_seconds=60, context=context()
    )
    assert jobs.mark_uncertain(attempt, context=context())
    records = bind_cleanse_dispatch(jobs.records._engine)
    try:
        assert records.scope.system and records.scope.tenant_id is None
        rows = records.query(
            DATASET, RecordQuery(), PageRequest(), context=context()
        ).items
        assert {row["job_id"] for row in rows} == {ready.job_id, run.job_id}
        assert {row["scope_kind"] for row in rows} == {"knowledge", "run"}
        assert rows[0]["tenant_id"] == "tenant-a"
        assert "request_payload" not in rows[0] and "artifact" not in rows[0]
        with pytest.raises(InvalidInput):
            records.query(
                DATASET,
                RecordQuery(fields=("request_payload",)),
                PageRequest(),
                context=context(),
            )
        with pytest.raises(ScopeDenied):
            records.create(DATASET, {}, context=context())
    finally:
        records.close()
