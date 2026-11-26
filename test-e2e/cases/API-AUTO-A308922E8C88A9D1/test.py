# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

import uuid

import pytest

from management.db.knowledge_base.repository import get_knowledge_record
from management.db.knowledge_base.file_lifecycle import create_file_record, delete_file_record, get_file_record
from management.db.model.repository import get_model_records
from shared.http import MODEL_TIMEOUT, assert_status, client, response_message
from shared.factories.ownership import register_owned_http


@pytest.mark.case_id("API-AUTO-A308922E8C88A9D1")
@pytest.mark.stage("D2")
@pytest.mark.asyncio
async def test_delete_documents_file_id_contract(tenant_a_admin, tenant_b_admin):
    run_id = uuid.uuid4().hex[:8]
    kb_name = f"del_doc_{run_id}"
    index_name = None
    seeded_file_ids = []

    models = get_model_records(None, tenant_a_admin.tenant_id) or []
    embedding_model_id = next(
        (
            model["model_id"]
            for model in models
            if model.get("model_type") in ("embedding", "multi_embedding")
        ),
        None,
    )
    assert embedding_model_id is not None, "no embedding model available to create a knowledge base"

    try:
        async with client("config", token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
            created = await api.post(
                f"/indices/{kb_name}",
                json={"embedding_model_id": embedding_model_id},
            )
        assert_status(created, (200, 201))

        knowledge_record = get_knowledge_record(
            {"knowledge_name": kb_name, "tenant_id": tenant_a_admin.tenant_id}
        )
        assert knowledge_record, f"created knowledge base {kb_name!r} has no record"
        index_name = knowledge_record["index_name"]
        knowledge_id = knowledge_record["knowledge_id"]
        register_owned_http(tenant_a_admin, 'owned_knowledge_bases', index_name,
                            f'/indices/{index_name}')

        # Manual chunk maintenance: create -> list -> update -> delete. The
        # manual chunk content is what the UI downloads, so the round-trip is
        # asserted here instead of a separate download endpoint.
        chunk_content = f"manual chunk content {run_id}"
        chunk_updated = f"manual chunk updated {run_id}"
        async with client("config", token=tenant_a_admin.access_token) as api:
            created_chunk = await api.post(
                f"/indices/{index_name}/chunk",
                json={
                    "content": chunk_content,
                    "title": f"chunk-{run_id}",
                    "filename": f"manual_{run_id}.txt",
                    "path_or_url": f"manual/manual_{run_id}.txt",
                },
            )
        assert_status(created_chunk, 200)
        chunk_id = (created_chunk.json() or {}).get("chunk_id")
        assert chunk_id, f"chunk creation returned no id: {created_chunk.text}"

        async def _list_chunks():
            async with client("config", token=tenant_a_admin.access_token) as api:
                response = await api.post(
                    f"/indices/{index_name}/chunks",
                    params={"page": 1, "page_size": 100},
                )
            assert_status(response, 200)
            return response.json().get("chunks", [])

        listed_chunks = await _list_chunks()
        listed = next((item for item in listed_chunks if str(item.get("id")) == str(chunk_id)), None)
        assert listed is not None, "created chunk is missing from the index listing"
        assert listed.get("content") == chunk_content
        assert listed.get("title") == f"chunk-{run_id}"

        async with client("config", token=tenant_a_admin.access_token) as api:
            updated_chunk = await api.put(
                f"/indices/{index_name}/chunk/{chunk_id}",
                json={"content": chunk_updated},
            )
        assert_status(updated_chunk, 200)
        updated_listing = await _list_chunks()
        updated = next((item for item in updated_listing if str(item.get("id")) == str(chunk_id)), None)
        assert updated is not None, "updated chunk disappeared from the index listing"
        assert updated.get("content") == chunk_updated
        assert updated.get("title") == f"chunk-{run_id}"

        async with client("config", token=tenant_a_admin.access_token) as api:
            deleted_chunk = await api.delete(f"/indices/{index_name}/chunk/{chunk_id}")
        assert_status(deleted_chunk, 200)
        remaining = await _list_chunks()
        assert all(str(item.get("id")) != str(chunk_id) for item in remaining), (
            "deleted chunk is still listed"
        )

        async with client("config", token=tenant_a_admin.access_token) as api:
            missing = await api.delete(f"/indices/{index_name}/documents")
        assert_status(missing, 400)
        assert response_message(missing) == "Either path_or_url or file_id is required"

        no_object = create_file_record(
            file_id=None,
            tenant_id=tenant_a_admin.tenant_id,
            knowledge_id=knowledge_id,
            index_name=index_name,
            original_filename=f"no_object_{run_id}.txt",
            status="COMPLETED",
            stage="DONE",
            created_by=tenant_a_admin.user_id,
        )
        seeded_file_ids.append(no_object["file_id"])

        async with client("config", token=tenant_a_admin.access_token) as api:
            source_only = await api.delete(
                f"/indices/{index_name}/documents",
                params={"file_id": no_object["file_id"], "scope": "source_only"},
            )
        assert_status(source_only, 400)
        assert response_message(source_only) == (
            "A file without a storage object can only use full deletion"
        )

        still_active = get_file_record(
            file_id=no_object["file_id"],
            index_name=index_name,
            tenant_id=tenant_a_admin.tenant_id,
            include_hidden=True,
        )
        assert still_active is not None, "rejected source_only deletion must not remove the record"

        async with client("config", token=tenant_a_admin.access_token) as api:
            full_delete = await api.delete(
                f"/indices/{index_name}/documents",
                params={"file_id": no_object["file_id"], "scope": "full"},
            )
        assert_status(full_delete, 200)
        assert not full_delete.json().get("deletion_pending"), (
            "full deletion returned a retry state"
        )

        terminal = get_file_record(
            file_id=no_object["file_id"],
            index_name=index_name,
            tenant_id=tenant_a_admin.tenant_id,
            include_hidden=True,
        )
        assert terminal is None or terminal.get("status") in ("DELETED", "DELETE_REQUESTED")

        victim = create_file_record(
            file_id=None,
            tenant_id=tenant_a_admin.tenant_id,
            knowledge_id=knowledge_id,
            index_name=index_name,
            original_filename=f"victim_{run_id}.txt",
            status="COMPLETED",
            stage="DONE",
            created_by=tenant_a_admin.user_id,
        )
        seeded_file_ids.append(victim["file_id"])

        async with client("config", token=tenant_b_admin.access_token) as api:
            cross = await api.delete(
                f"/indices/{index_name}/documents",
                params={"file_id": victim["file_id"], "scope": "full"},
            )
        assert cross.status_code in (401, 403), f"expected 401/403, got {cross.status_code}"

        intact = get_file_record(
            file_id=victim["file_id"],
            index_name=index_name,
            tenant_id=tenant_a_admin.tenant_id,
            include_hidden=True,
        )
        assert intact is not None, "cross-tenant delete removed the target record"
        assert intact.get("status") not in ("DELETED", "DELETE_REQUESTED")
    finally:
        for file_id in seeded_file_ids:
            try:
                delete_file_record(file_id)
            except Exception:
                pass
        if index_name:
            try:
                async with client("config", token=tenant_a_admin.access_token) as api:
                    await api.delete(f"/indices/{index_name}")
            except Exception:
                pass
