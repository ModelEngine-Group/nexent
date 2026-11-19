# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-USAGE-02 keep quota telemetry scalar-only and model-free."""

import pytest
from contracts.knowledge_collections import (
    KnowledgeCollectionsDescribe,
    KnowledgeCollectionsUsage,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied, Unavailable
from nexent.storage.models import VectorCollectionStatistics, VectorFieldStatistics
from pydantic import ValidationError
from runtime.knowledge_base.collection_usage import KnowledgeCollectionUsageService

from test.backend.services.test_collection_metadata_runtime import (
    boundary,  # noqa: F401
)


def service(s):
    for key, port in s.vectors.items():
        port.statistics.return_value = VectorCollectionStatistics(
            "one" if key == 1 else "two",
            4,
            10,
            100,
            20,
            5,
            (VectorFieldStatistics("source", 2, ("private-path",)),),
        )
    return KnowledgeCollectionUsageService(s.client, ports=s.ports)


def request(s):
    return KnowledgeCollectionsUsage(
        knowledge_ids=s.request.knowledge_ids,
        expected_revisions=s.request.expected_revisions,
    )


async def test_only_three_metrics_are_returned_without_model_or_body_reads(boundary):  # noqa: F811
    s = boundary
    result = await service(s).describe(request(s), s.actor)
    assert [item.knowledge_id for item in result.items] == [2, 1]
    assert result.items[0].statistics.model_dump() == {
        "record_count": 4,
        "size_bytes": 10,
        "source_count": 2,
    }
    assert (
        "private-path" not in result.model_dump_json()
        and "model" not in result.model_dump_json()
    )
    assert s.opened == s.closed == [2, 1] and s.contexts[0].cancelled.is_set()
    for port in s.vectors.values():
        port.describe_collection.assert_not_called()
        fields = port.statistics.call_args.args[1]
        assert len(fields) == 1 and fields[0].name == "source"
    assert s.client.authorize_collection_metadata.await_count == 2
    assert all(
        c.args[0].view == "usage" and c.args[1:] == ("reader", "tenant-a")
        for c in s.client.authorize_collection_metadata.await_args_list
    )
    s.display.assert_not_called()


async def test_missing_collection_and_unavailable_statistics_are_distinct(boundary):  # noqa: F811
    s = boundary
    worker = service(s)
    s.vectors[1].collection_exists.return_value = False
    s.vectors[2].statistics.side_effect = Unavailable()
    result = await worker.describe(request(s), s.actor)
    assert result.items[0].present and result.items[0].statistics_error == "unavailable"
    assert result.items[0].statistics is None
    assert (
        not result.items[1].present
        and result.items[1].statistics is None
        and result.items[1].statistics_error is None
    )
    s.vectors[1].statistics.assert_not_called()


async def test_changed_authorization_refuses_result(boundary):  # noqa: F811
    s = boundary
    changed = s.grants.model_copy(deep=True)
    changed.knowledge_bases[0].collection = "changed"
    s.client.authorize_collection_metadata.side_effect = [s.grants, changed]
    with pytest.raises(Conflict):
        await service(s).describe(request(s), s.actor)


@pytest.mark.parametrize(
    "extra",
    [
        {"view": "resources"},
        {"include_statistics": True},
        {"query": {}},
        {"model_id": 1},
    ],
)
def test_usage_contract_refuses_other_views_and_provider_fields(extra):
    with pytest.raises(ValidationError):
        KnowledgeCollectionsUsage.model_validate(
            dict(knowledge_ids=[1], expected_revisions={1: "a" * 64}, **extra)
        )


def test_original_describe_cannot_be_used_for_quota_view():
    with pytest.raises(ValidationError):
        KnowledgeCollectionsDescribe(
            knowledge_ids=[1], expected_revisions={1: "a" * 64}, view="usage"
        )


async def test_usage_callback_deadline_cancels_once_before_provider(boundary,caplog):  # noqa: F811
    import asyncio
    s=boundary;worker=service(s);worker.seconds=.03
    async def slow(*args):
        await asyncio.sleep(1)
    s.client.authorize_collection_metadata.side_effect=slow
    with pytest.raises(DeadlineExceeded):
        await worker.describe(request(s),s.actor)
    assert not s.opened
    assert sum('knowledge_collection_describe_timeout' in r.message and r.levelname=='WARNING' for r in caplog.records)==1


async def test_foreign_provider_scope_is_rejected(boundary):  # noqa: F811
    s=boundary;worker=service(s)
    s.vectors[2].scope.tenant_id='wrong'
    with pytest.raises(ScopeDenied):
        await worker.describe(request(s),s.actor)
    s.vectors[2].statistics.assert_not_called()
