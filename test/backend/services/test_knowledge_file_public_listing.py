# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-PAGE-01/02 retain file projections through AgentOS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_sources import KnowledgeSourcesResult
from management.services.knowledge_base.file_listing import KnowledgeFileListing
from management.services.knowledge_base.file_source_display import FileSourceDisplay
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_search import knowledge_search_revision


@pytest.fixture
async def listing():
    actor = ServicePrincipal("reader", "tenant-a")
    row = {
        "knowledge_id": 1,
        "index_name": "kb",
        "tenant_id": "tenant-a",
        "deletion_request": None,
        "knowledge_sources": "elasticsearch",
        "embedding_model_id": 3,
        "ingroup_permission": "PRIVATE",
        "group_ids": "",
        "created_by": "reader",
        "delete_flag": "N",
    }
    revision = knowledge_search_revision(row)
    reader = SimpleNamespace(
        knowledge=Mock(side_effect=lambda *a, **kw: dict(row)),
        files=Mock(return_value=[]),
    )
    response = KnowledgeSourcesResult(
        knowledge_id=1,
        revision=revision,
        present=True,
        sources=[
            {
                "source_key": "source",
                "path_or_url": "source",
                "filename": ["original", None],
                "file_size": "stored-size",
                "create_time": "2025-01-02T03:04:05",
                "chunk_count": 4,
            }
        ],
    )
    client = SimpleNamespace(list_knowledge_sources=AsyncMock(return_value=response))
    display = SimpleNamespace(project=Mock(wraps=FileSourceDisplay().project))
    manager = ThreadManager(
        service_name="file-list-unit",
        lane_policies={"control-io": LanePolicy("control-io", 1, 8)},
    )
    manager.start()
    set_default_thread_manager(manager)
    service = KnowledgeFileListing(reader=reader, client=client, display=display)
    try:
        yield SimpleNamespace(**locals())
    finally:
        assert not (await manager.shutdown(timeout=3)).stuck_execution_ids
        clear_default_thread_manager(manager)


async def test_original_projection_and_actual_actor_without_models_or_native_vector(
    listing,
):
    s = listing
    result = await s.service.list("kb", s.actor)
    assert result == {
        "files": [
            {
                "path_or_url": "source",
                "file": ["original", None],
                "file_size": "stored-size",
                "create_time": 1735787045000,
                "status": "COMPLETED",
                "latest_task_id": "",
                "chunk_count": 4,
                "error_reason": None,
                "has_error_info": False,
                "chunks": [],
                "source_available": True,
            }
        ]
    }
    request, user, tenant = s.client.list_knowledge_sources.await_args.args
    assert (
        request.knowledge_id,
        request.expected_revision,
        request.limit,
        user,
        tenant,
    ) == (1, s.revision, 1000, "reader", "tenant-a")
    assert s.reader.knowledge.call_count == 2
    assert all(
        call.args == ("kb", s.actor) for call in s.reader.knowledge.call_args_list
    )
    assert s.display.project.call_args.args[1] == s.actor


async def test_lifecycle_merges_physical_count_and_hides_deleted_source(listing):
    s = listing
    s.reader.files.return_value = [
        {
            "file_id": "f",
            "knowledge_id": 1,
            "tenant_id": "tenant-a",
            "object_name": "source",
            "original_filename": "old",
            "status": "FORWARDING",
            "runtime_status": "queued",
            "file_size": 8,
            "uploaded_at": "2025-01-01T00:00:00+00:00",
            "forward_task_id": "new-task",
            "update_time": "1",
        }
    ]
    result = await s.service.list("kb", s.actor)
    file = result["files"][0]
    assert (
        file["status"],
        file["file"],
        file["chunk_count"],
        file["latest_task_id"],
        file["file_size"],
    ) == ("WAIT_FOR_FORWARDING", ["original", None], 4, "new-task", 8)
    s.reader.files.return_value[0]["status"] = "DELETED"
    assert await s.service.list("kb", s.actor) == {"files": []}


async def test_missing_collection_still_displays_pending_file(listing):
    s = listing
    s.client.list_knowledge_sources.return_value = KnowledgeSourcesResult(
        knowledge_id=1, revision=s.revision, present=False, sources=[]
    )
    s.reader.files.return_value = [
        {
            "file_id": "f",
            "knowledge_id": 1,
            "tenant_id": "tenant-a",
            "object_name": "pending",
            "original_filename": "name",
            "status": "UPLOADED",
        }
    ]
    files = (await s.service.list("kb", s.actor))["files"]
    assert len(files) == 1 and files[0]["status"] == "WAIT_FOR_PROCESSING"
    assert files[0]["chunks"] == [] and files[0]["chunk_count"] == 0


@pytest.mark.parametrize(
    "change", ["identity", "revision", "authorization", "file-tenant"]
)
async def test_changed_or_foreign_results_are_rejected(listing, change):
    s = listing
    if change == "identity":
        s.client.list_knowledge_sources.return_value = s.response.model_copy(
            update={"knowledge_id": 9}
        )
    elif change == "revision":
        s.client.list_knowledge_sources.return_value = s.response.model_copy(
            update={"revision": "b" * 64}
        )
    elif change == "authorization":
        s.reader.knowledge.side_effect = [s.row, ScopeDenied()]
    else:
        s.reader.files.return_value = [
            {"file_id": "f", "knowledge_id": 1, "tenant_id": "foreign"}
        ]
    with pytest.raises((Conflict, ScopeDenied)):
        await s.service.list("kb", s.actor)


async def test_provider_failure_propagates_without_empty_success_or_retry(listing):
    s = listing
    s.client.list_knowledge_sources.side_effect = Conflict()
    with pytest.raises(Conflict):
        await s.service.list("kb", s.actor)
    assert s.client.list_knowledge_sources.await_count == 1
    s.display.project.assert_not_called()


async def test_shared_resource_uses_actual_reader_for_both_sides(listing):
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID

    s = listing
    s.row["tenant_id"] = ASSET_OWNER_TENANT_ID
    s.row["ingroup_permission"] = "READ_ONLY"
    s.client.list_knowledge_sources.return_value = s.response.model_copy(
        update={"revision": knowledge_search_revision(s.row)}
    )
    assert len((await s.service.list("kb", s.actor))["files"]) == 1
    assert s.client.list_knowledge_sources.await_args.args[1:] == ("reader", "tenant-a")
    assert s.display.project.call_args.args[1] == s.actor


async def test_changed_resource_after_source_read_does_not_return_stale_page(listing):
    s = listing
    changed = dict(s.row, embedding_model_id=99)
    s.reader.knowledge.side_effect = [s.row, changed]
    with pytest.raises(Conflict):
        await s.service.list("kb", s.actor)
    assert s.client.list_knowledge_sources.await_count == 1


@pytest.mark.parametrize("seconds", [0, True, 181, float("inf")])
def test_invalid_total_budget_is_rejected(seconds):
    from nexent.storage.errors import InvalidInput

    with pytest.raises(InvalidInput):
        KnowledgeFileListing(operation_seconds=seconds)


@pytest.mark.parametrize("value", [None, "invalid", {"raw": "date"}])
async def test_invalid_original_time_uses_existing_current_time_rule(
    listing, value, mocker
):
    s = listing
    mocker.patch(
        "management.services.knowledge_base.file_listing.time.time", return_value=1234
    )
    source = s.response.sources[0].model_copy(update={"create_time": value})
    s.client.list_knowledge_sources.return_value = s.response.model_copy(
        update={"sources": [source]}
    )
    assert (await s.service.list("kb", s.actor))["files"][0]["create_time"] == 1234000


async def test_deadline_cancels_request_and_logs_once(listing, caplog):
    import asyncio

    s = listing

    async def slow(*args):
        await asyncio.sleep(1)

    s.client.list_knowledge_sources.side_effect = slow
    s.service.operation_seconds = 0.03
    with pytest.raises(DeadlineExceeded):
        await s.service.list("kb", s.actor)
    contexts = [call.kwargs["context"] for call in s.reader.knowledge.call_args_list]
    assert contexts and all(context.cancelled.is_set() for context in contexts)
    assert (
        len(
            [
                r
                for r in caplog.records
                if "knowledge_file_list_timeout" in r.message
                and r.levelname == "WARNING"
            ]
        )
        == 1
    )
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
