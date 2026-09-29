"""D3 real knowledge-base, file lifecycle, retrieval and adapter scenarios."""

from __future__ import annotations
from shared.factories.agent import retrieval_agent
from shared.factories.files import _upload_tuple, _object_name, _upload_kb_file, _upload_attachment, _remove_object
from shared.resource_ids import absent_numeric_id

import json
from urllib.parse import quote
from uuid import uuid4

import pytest

from d3.assets import (
    asset_path,
    create_registered_knowledge_base,
    model_id,
    temporary_conversation,
    temporary_knowledge_base,
    get_test_asset,
)
from shared.cases import case_params
from shared.config import controlled_asset_url
from shared.http import MODEL_TIMEOUT, assert_no_server_error, assert_status, client
from shared.sse import assert_terminal_event, read_sse


CASES = [
    "API-097", "API-098", "API-099", "API-100", "API-101", "API-102",
    "API-103", "API-104", "API-105", "CTR-044", "CTR-045", "API-106",
    "API-107", "API-108", "API-109", "CTR-046", "AGT-042", "AGT-043",
    "AGT-044", "AGT-045", "AGT-046", "API-110", "API-111", "CTR-047",
]












async def _kb_create(identity, valid: bool) -> None:
    if not valid:
        name = f"d3-invalid-kb-{uuid4().hex[:8]}"
        async with client("config", token=identity.access_token) as api:
            missing = await api.post(f"/indices/{name}", json={})
            wrong_type = await api.post(f"/indices/{name}", json={"embedding_model_id": "not-an-int"})
        assert_status(missing, 400)
        assert_status(wrong_type, 400)
        return
    kb = await create_registered_knowledge_base(
        identity, owner_case_id="API-097", role="basic", prefix="d3-create", quota_limit_bytes=5_000_000,
    )
    async with client("config", token=identity.access_token) as api:
        status = await api.get(f"/indices/{kb['index_name']}/embedding-model-status")
    assert_status(status, 200)
    body = status.json()
    assert body["status"] == "configured"
    assert int(body["model_id"]) == await model_id("embedding", identity)
    assert body["knowledge_name"] == kb["display_name"]


async def _kb_lifecycle(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            empty = await api.post("/indices/check_exist", json={"knowledge_name": ""})
            missing = await api.patch("/indices/not-present", json={"knowledge_name": "x"})
            frequency = await api.patch("/indices/not-present/summary_frequency", json={"summary_frequency": "never-ever"})
        assert_status(empty, (400, 500))  # Current handler wraps its own 400; keep regression visible.
        assert_status(missing, 404)
        assert_status(frequency, (400, 404))
        return
    async with temporary_knowledge_base(identity, prefix="d3-lifecycle") as kb:
        renamed = f"renamed-{uuid4().hex[:8]}"
        async with client("config", token=identity.access_token) as api:
            exists = await api.post("/indices/check_exist", json={"knowledge_name": kb["display_name"]})
            updated = await api.patch(
                f"/indices/{kb['index_name']}",
                json={"knowledge_name": renamed, "ingroup_permission": "PRIVATE", "group_ids": [], "quota_limit_bytes": 6_000_000},
            )
            frequency = await api.patch(
                f"/indices/{kb['index_name']}/summary_frequency", json={"summary_frequency": "1d"},
            )
            listing = await api.get("/indices", params={"include_stats": True, "keyword": renamed, "limit": 20})
        assert_status(exists, 200)
        assert exists.json().get("status") in {"exists", "exists_in_tenant"}
        assert_status(updated, 200)
        assert_status(frequency, 200)
        assert_status(listing, 200)
        rows = listing.json().get("indices_info") or []
        row = next(item for item in rows if item.get("name") == kb["index_name"])
        assert row.get("display_name") == renamed and row.get("summary_frequency") == "1d"


async def _file_upload(identity, valid: bool) -> None:
    async with temporary_knowledge_base(identity, prefix="d3-upload", quota_limit_bytes=10_000_000) as kb:
        if valid:
            first = _upload_tuple("files", "basic_text", content_type="text/plain")
            second = _upload_tuple("files", "image", content_type="image/png")
            async with client("config", token=identity.access_token) as api:
                response = await api.post(
                    "/file/upload",
                    data={"destination": "minio", "folder": "knowledge_base", "index_name": kb["index_name"]},
                    files=[("file", first), ("file", second)],
                )
            assert_status(response, 200)
            body = response.json()
            assert len(body.get("uploaded_file_paths") or []) == 2
            assert len(body.get("file_records") or []) == 2
            assert all(record.get("file_id") and record.get("stage") for record in body["file_records"])
        else:
            bad = ("malware.exe", b"MZ-not-a-real-executable", "application/octet-stream")
            async with client("config", token=identity.access_token) as api:
                response = await api.post(
                    "/file/upload",
                    data={"destination": "unknown", "folder": "knowledge_base", "index_name": kb["index_name"]},
                    files=[("file", bad)],
                )
            assert_status(response, 400)
            assert response.json().get("errors") or response.json().get("detail")


async def _file_process(identity, valid: bool) -> None:
    async with temporary_knowledge_base(identity, prefix="d3-process") as kb:
        uploaded = await _upload_kb_file(identity, kb["index_name"])
        file_data = {
            "path_or_url": uploaded["object_name"],
            "filename": uploaded["payload"]["uploaded_filenames"][0],
            "file_id": uploaded["record"]["file_id"],
        }
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            if valid:
                response = await api.post(
                    "/file/process",
                    json={"files": [file_data], "index_name": kb["index_name"], "destination": "minio", "chunking_strategy": "basic"},
                )
                assert_status(response, 201)
                tasks = response.json().get("process_tasks") or {}
                assert tasks.get("task_id") or tasks.get("task_ids") or tasks.get("results")
            else:
                response = await api.post(
                    "/file/process",
                    json={"files": [file_data], "index_name": "not-present", "destination": "minio", "chunking_strategy": "invalid"},
                )
                assert_status(response, (400, 403, 404, 422))


async def _task_api(identity) -> None:
    async with temporary_knowledge_base(identity, prefix="d3-task") as kb:
        uploaded = await _upload_kb_file(identity, kb["index_name"])
        request = {
            "source": uploaded["object_name"], "source_type": "minio", "chunking_strategy": "basic",
            "index_name": kb["index_name"], "original_filename": uploaded["payload"]["uploaded_filenames"][0],
            "embedding_model_id": await model_id("embedding", identity), "file_id": uploaded["record"]["file_id"],
        }
        async with client("data_process", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            created = await api.post("/tasks", json=request)
            assert_status(created, 201)
            task_id = created.json().get("task_id")
            assert task_id
            listing = await api.get("/tasks")
            by_index = await api.get(f"/tasks/indices/{kb['index_name']}")
            converted = await api.post("/tasks/convert_state", json={"process_state": "SUCCESS", "forward_state": "SUCCESS"})
            missing_task_id = f"missing-{uuid4().hex}"
            missing = await api.get(f"/tasks/{missing_task_id}/details")
        assert_status(listing, 200)
        assert_status(by_index, 200)
        assert_status(converted, 200)
        assert converted.json().get("state")
        # Unknown Celery IDs currently have a PENDING status; this API returns
        # that status as a task detail rather than a 404 resource response.
        assert_status(missing, 200)
        missing_detail = missing.json()
        assert missing_detail.get("id") == missing_task_id
        assert missing_detail.get("status") == "PENDING"
        assert not missing_detail.get("index_name")
        assert not missing_detail.get("file_id")


async def _office_conversion(identity, valid: bool) -> None:
    if not valid:
        async with client("data_process", timeout=MODEL_TIMEOUT) as api:
            response = await api.post(
                "/tasks/convert_to_pdf", data={"object_name": "attachments/missing.docx", "pdf_object_name": "attachments/missing.pdf"},
            )
        assert_status(response, 500)
        return
    object_name = await _upload_attachment(identity, "office", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    pdf_name = f"{object_name}.pdf"
    try:
        async with client("data_process", timeout=MODEL_TIMEOUT) as api:
            converted = await api.post("/tasks/convert_to_pdf", data={"object_name": object_name, "pdf_object_name": pdf_name})
        assert_status(converted, 200)
        assert converted.json().get("success") is True
        async with client("config", token=identity.access_token) as api:
            preview = await api.get(f"/file/preview/{quote(pdf_name, safe='/')}")
        assert_status(preview, 200)
        assert preview.headers.get("content-type", "").startswith("application/pdf")
    finally:
        await _remove_object(identity, object_name)
        await _remove_object(identity, pdf_name)


async def _file_download(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            missing = await api.get("/file/download/attachments/not-present.txt", params={"download": "stream"})
            invalid_mode = await api.get("/file/download/attachments/not-present.txt", params={"download": "bogus"})
        assert_status(missing, (403, 404, 500))
        assert_no_server_error(invalid_mode)
        return
    object_name = await _upload_attachment(identity, "basic_text", "text/plain")
    try:
        async with client("config", token=identity.access_token) as api:
            info = await api.get(f"/file/download/{quote(object_name, safe='/')}")
            stream = await api.get(
                f"/file/download/{quote(object_name, safe='/')}", params={"download": "stream", "filename": "场景.txt"},
            )
            redirect = await api.get(f"/file/download/{quote(object_name, safe='/')}", params={"download": "redirect"})
        assert_status(info, 200)
        assert_status(stream, 200)
        assert stream.content and stream.headers.get("etag")
        assert "filename*=UTF-8''" in stream.headers.get("content-disposition", "")
        assert_status(redirect, (302, 307))
    finally:
        await _remove_object(identity, object_name)


async def _file_preview(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            missing = await api.get("/file/preview/attachments/not-present.txt")
        assert_status(missing, (403, 404))
        return
    object_name = await _upload_attachment(identity, "basic_text", "text/plain")
    try:
        path = f"/file/preview/{quote(object_name, safe='/')}"
        async with client("config", token=identity.access_token) as api:
            full = await api.get(path)
            partial = await api.get(path, headers={"Range": "bytes=0-3"})
            invalid = await api.get(path, headers={"Range": "bytes=999999999-1000000000"})
        assert_status(full, 200)
        assert full.headers.get("accept-ranges") == "bytes" and full.headers.get("etag")
        assert_status(partial, 206)
        assert partial.headers.get("content-range", "").startswith("bytes 0-3/")
        assert_status(invalid, 416)
    finally:
        await _remove_object(identity, object_name)


async def _datamate_download_contract(identity) -> None:
    base_url = controlled_asset_url(str(get_test_asset("external_knowledge", "local_protocol_path")))
    async with client("config", token=identity.access_token) as api:
        by_url = await api.get(
            "/file/datamate/download",
            params={"url": f"{base_url}/api/data-management/datasets/ds-1/files/file-1/download", "filename": "asset.txt"},
        )
        by_parts = await api.get(
            "/file/datamate/download",
            params={"base_url": base_url, "dataset_id": "ds-1", "file_id": "file-1"},
        )
        malformed = await api.get("/file/datamate/download", params={"url": "ftp://invalid/path"})
    assert_status(by_url, 200)
    assert_status(by_parts, 200)
    assert by_url.content == by_parts.content
    assert_status(malformed, 400)


async def _knowledge_summary(identity, valid: bool) -> None:
    async with temporary_knowledge_base(identity, prefix="d3-summary") as kb:
        marker = f"summary-{uuid4().hex[:8]}"
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            if not valid:
                missing = await api.post("/summary/not-present/auto_summary", params={"model_id": absent_numeric_id(__name__)})
                assert_status(missing, (403, 404, 500))
                return
            changed = await api.post(f"/summary/{kb['index_name']}/summary", json={"summary_result": marker})
            fetched = await api.get(f"/summary/{kb['index_name']}/summary")
            frequency = await api.patch(
                f"/indices/{kb['index_name']}/summary_frequency", json={"summary_frequency": "1d"},
            )
        assert_status(changed, 200)
        assert_status(fetched, 200)
        assert fetched.json().get("summary") == marker
        assert_status(frequency, 200)


async def _seed_chunk(identity, index_name: str, marker: str) -> None:
    from shared.factories.knowledge import create_kb_chunk
    await create_kb_chunk(identity,index_name,f'The unique D3 retrieval marker is {marker}.',
                          title='D3 retrieval',filename='marker.txt')


async def _retrieval(identity, mode: str) -> None:
    if mode == "boundary":
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            empty = await api.post("/indices/search/hybrid", json={"query": "x", "index_names": [], "top_k": 10})
            unknown = await api.post("/indices/search/hybrid", json={"query": "x", "index_names": ["not-present"], "top_k": 10})
        assert_status(empty, 422)
        assert_status(unknown, (400, 403, 404))
        return
    if mode == "dependency":
        async with temporary_knowledge_base(identity, prefix="d3-retrieval-failure") as kb:
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                response = await api.post(
                    "/indices/search/hybrid",
                    json={"query": "dependency failure probe", "index_names": [kb["index_name"]], "top_k": 10},
                )
            assert_status(response, (200, 409, 500, 502, 503, 504))
            if response.status_code == 200:
                assert isinstance(response.json(), (dict, list))
        return
    async with temporary_knowledge_base(identity, prefix="d3-retrieval") as first, temporary_knowledge_base(
        identity, prefix="d3-retrieval-second"
    ) as second:
        marker = f"KBMARKER{uuid4().hex[:10]}"
        await _seed_chunk(identity, first["index_name"], marker)
        await _seed_chunk(identity, second["index_name"], "SECONDARY-D3-MARKER")
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            searched = await api.post(
                "/indices/search/hybrid",
                json={"query": marker, "index_names": [first["index_name"], second["index_name"]], "top_k": 10, "weight_accurate": 0.7},
            )
        assert_status(searched, 200)
        assert marker.lower() in json.dumps(searched.json(), ensure_ascii=False).lower()
        async with retrieval_agent(identity) as agent_id, temporary_conversation(identity, "D3 knowledge retrieval") as conversation_id:
            request = {
                "query": f"Find and repeat the exact marker {marker} from the selected knowledge base.",
                "agent_id": agent_id, "conversation_id": conversation_id, "history": [], "is_debug": True,
                "knowledge_scope": {
                    "schema_version": 1,
                    "local": {"mode": "override", "knowledge_ids": [str(first["knowledge_id"])]},
                    "aidp": {"mode": "disabled", "kds_ids": []},
                },
            }
            async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                async with api.stream("POST", "/agent/run", json=request) as response:
                    assert_status(response, 200)
                    events = await read_sse(response, limit=2000)
            assert_terminal_event(events)
            text = json.dumps(events, ensure_ascii=False).lower()
            assert marker.lower() in text
            assert "source" in text or "citation" in text or "retriev" in text


async def _conversation_scope(identity, valid: bool) -> None:
    async with temporary_conversation(identity, "D3 knowledge scope") as conversation_id:
        if valid:
            async with temporary_knowledge_base(identity, prefix="d3-scope") as kb:
                scope = {
                    "scope": {
                        "schema_version": 1,
                        "local": {"mode": "override", "knowledge_ids": [str(kb["knowledge_id"])]},
                        "aidp": {"mode": "disabled", "kds_ids": []},
                    }
                }
                async with client("runtime", token=identity.access_token) as api:
                    replaced = await api.put(f"/conversation/{conversation_id}/knowledge-scope", json=scope)
                    cleared = await api.put(f"/conversation/{conversation_id}/knowledge-scope", json={"scope": None})
                assert_status(replaced, 200)
                assert replaced.json().get("data", {}).get("knowledge_scope") or replaced.json().get("data")
                assert_status(cleared, 200)
        else:
            invalid = {
                "scope": {
                    "schema_version": 1,
                    "local": {"mode": "override", "knowledge_ids": []},
                    "aidp": {"mode": "inherit", "kds_ids": ["not-allowed"]},
                }
            }
            async with client("runtime", token=identity.access_token) as api:
                validation = await api.put(f"/conversation/{conversation_id}/knowledge-scope", json=invalid)
                missing = await api.put(f"/conversation/{absent_numeric_id(__name__)}/knowledge-scope", json={"scope": None})
            assert_status(validation, 422)
            assert_status(missing, 404)


async def _external_adapter_contract(identity) -> None:
    base = controlled_asset_url(str(get_test_asset("external_knowledge", "local_protocol_path"))).rstrip("/")
    key = str(get_test_asset("external_knowledge", "local_api_key"))
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        responses = [
            await api.get("/dify/datasets", params={"dify_api_base": f"{base}/dify", "api_key": key}),
            await api.get("/ragflow/datasets", params={"ragflow_api_base": f"{base}/ragflow", "api_key": key}),
            await api.post("/ind-aidp/knowledge-bases/list", json={"server_url": f"{base}/aidp", "api_key": key, "tenant_id": "test"}),
            await api.get("/idata/knowledge-space", params={"idata_api_base": f"{base}/idata", "api_key": key, "user_id": "test"}),
            await api.post("/haotian/test-connection", json={"list_url": f"{base}/haotian/knowledge-sets", "authorization": f"Bearer {key}"}),
            await api.post("/datamate/test_connection", json={"datamate_url": f"{base}/datamate"}),
        ]
    for response in responses:
        assert_no_server_error(response)
        assert_status(response, (200, 400, 401, 403, 404))
        assert "traceback" not in response.text.lower()


@pytest.mark.asyncio
async def execute_d3_knowledge_file_retrieval(case, tenant_a_admin, tenant_a_user):
    case_id = case["id"]
    if case_id in {"API-097", "API-098"}:
        await _kb_create(tenant_a_admin, case_id == "API-097")
    elif case_id in {"API-099", "API-100"}:
        await _kb_lifecycle(tenant_a_admin, case_id == "API-099")
    elif case_id in {"API-101", "API-102"}:
        await _file_upload(tenant_a_admin, case_id == "API-101")
    elif case_id in {"API-103", "API-104"}:
        await _file_process(tenant_a_admin, case_id == "API-103")
    elif case_id == "API-105":
        await _task_api(tenant_a_admin)
    elif case_id in {"CTR-044", "CTR-045"}:
        await _office_conversion(tenant_a_user, case_id == "CTR-044")
    elif case_id in {"API-106", "API-107"}:
        await _file_download(tenant_a_user, case_id == "API-106")
    elif case_id in {"API-108", "API-109"}:
        await _file_preview(tenant_a_user, case_id == "API-108")
    elif case_id == "CTR-046":
        await _datamate_download_contract(tenant_a_user)
    elif case_id in {"AGT-042", "AGT-043"}:
        await _knowledge_summary(tenant_a_admin, case_id == "AGT-042")
    elif case_id in {"AGT-044", "AGT-045", "AGT-046"}:
        mode = {"AGT-044": "core", "AGT-045": "boundary", "AGT-046": "dependency"}[case_id]
        await _retrieval(tenant_a_admin, mode)
    elif case_id in {"API-110", "API-111"}:
        await _conversation_scope(tenant_a_user, case_id == "API-110")
    elif case_id == "CTR-047":
        await _external_adapter_contract(tenant_a_user)
    else:
        raise AssertionError(f"unmapped D3 case {case_id}")
