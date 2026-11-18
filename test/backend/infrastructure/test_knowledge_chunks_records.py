# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resource-specific read views cannot mutate jobs or enumerate other KBs."""

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery

from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs
from test.backend.services.test_knowledge_jobs import setup as setup  # noqa: PLC0414


def test_exact_resource_job_views_are_read_only(setup):
    service, records, engine, request, context, *_ = setup
    state = service.submit(request, context=context)
    port = bind_knowledge_jobs(records.scope, engine, knowledge_id=request.knowledge_id, writable=False)
    other = bind_knowledge_jobs(records.scope, engine, knowledge_id=2, writable=False)
    try:
        assert port.get(JOBS, state.job_id, context=context)['knowledge_id'] == request.knowledge_id
        assert other.get(JOBS, state.job_id, context=context) is None
        assert other.query(FILES, RecordQuery(), PageRequest(), context=context).items == ()
        with pytest.raises(ScopeDenied):
            port.patch(JOBS, state.job_id, FieldPatch(set_values={'status': 'failed'}), context=context)
        with pytest.raises(ScopeDenied):
            bind_knowledge_jobs(records.scope, engine, knowledge_id=1, writable=True)
    finally:
        port.close()
        other.close()
