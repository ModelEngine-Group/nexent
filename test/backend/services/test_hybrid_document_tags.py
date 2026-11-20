# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from management.services.knowledge_base.hybrid_tags import filter_hybrid_tags
from management.services.tag.identity import _encode_document_resource_id

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.document_tag_records import TABLES
from infrastructure.rdb.hybrid_document_tags import (
    PROJECTIONS,
    bind_hybrid_document_tags,
)


@pytest.fixture
def tag_fixture():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
    assignment = TABLES["assignment"]
    for table in (PROJECTIONS, assignment):
        table.create(engine)
    cases = [
        ("match", "tenant-a", "kb", "local", "synced", [(5, 3, "N"), (9, 4, "N")]),
        ("not-all", "tenant-a", "kb", "local", "synced", [(5, 3, "N"), (9, 4, "Y")]),
        ("pending", "tenant-a", "kb", "local", "pending", [(5, 3, "N"), (9, 4, "N")]),
        ("wrong", "tenant-b", "kb", "local", "synced", [(5, 3, "N"), (9, 4, "N")]),
        ("external", "tenant-a", "kb", "aidp", "synced", [(5, 3, "N"), (9, 4, "N")]),
        ("elsewhere", "tenant-a", "other-kb", "local", "synced", [(5, 3, "N"), (9, 4, "N")]),
    ]
    with engine.begin() as connection:
        assignment_id = 0
        for projection_id, (path, tenant, index, provider, status, tags) in enumerate(cases, start=1):
            resource = _encode_document_resource_id(provider, index, path)
            connection.execute(PROJECTIONS.insert().values(
                projection_id=projection_id, tenant_id=tenant, provider=provider, knowledge_base_id=index,
                resource_id=resource, status=status,
            ))
            for definition, value, state in tags:
                assignment_id += 1
                connection.execute(assignment.insert().values(
                    assignment_id=assignment_id, tenant_id=tenant, resource_id=resource, resource_type="knowledge_document",
                    definition_id=definition, value_id=value, delete_flag=state,
                ))
    actor = ServicePrincipal("reader", "tenant-a")
    reads = []

    @contextmanager
    def ports(principal, index, groups, *, context):
        assert principal == actor
        reads.append((index, groups))
        records = bind_hybrid_document_tags(principal, index, groups, engine)
        try:
            yield records
        finally:
            records.close()

    try:
        yield actor, ports, reads
    finally:
        engine.dispose()


def test_filter_preserves_rank_and_requires_each_group_with_synced_local_projection(tag_fixture):
    actor, ports, reads = tag_fixture
    hits = [{"index": "kb", "path_or_url": path, "score": score}
            for score, path in enumerate(("not-all", "match", "pending", "wrong", "external", "elsewhere", "match"))]
    predicates = [{"definition_id": 5, "value_ids": [1, 2]}, {"definition_id": 5, "value_ids": ["3"]},
                  {"definition_id": 9, "value_ids": [4]}, {"definition_id": 7, "value_ids": []}]

    assert filter_hybrid_tags(hits, ["kb", "unused", "kb"], predicates, actor, ports=ports) == [hits[1], hits[6]]
    assert reads == [("kb", {5: [1, 2, 3], 9: [4]})]


def test_empty_value_groups_still_require_synced_local_projection(tag_fixture):
    actor, ports, _ = tag_fixture
    hits = [{"index": "kb", "path_or_url": path} for path in ("not-all", "pending", "match", "wrong", "external")]

    assert filter_hybrid_tags(hits, ["kb"], [{"definition_id": 7, "value_ids": []}], actor, ports=ports) == [hits[0], hits[2]]
