"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
from urllib.parse import quote, urlencode
from d3.assets import asset_path


def _upload_tuple(section: str, key: str, *, content_type: str | None = None):
    path = asset_path(section, key)
    return path.name, path.read_bytes(), content_type or "application/octet-stream"


def _object_name(payload: dict) -> str:
    paths = payload.get("uploaded_file_paths") or []
    if paths:
        return str(paths[0])
    for item in payload.get("results") or []:
        if item.get("success"):
            value = item.get("object_name") or item.get("path") or item.get("file_path")
            if value:
                return str(value)
    raise AssertionError(f"upload response omitted an object name: {payload}")


def register_uploaded_files(identity, payload, *, index_name=None):
    """Persist every returned owned ID before status/shape assertions can fail."""
    from shared.asset_registry import runtime_dir, register_asset
    if runtime_dir() is None:
        return
    if index_name is not None:
        uploaded_paths = payload.get('uploaded_file_paths') or []
        for position, record in enumerate(payload.get('file_records') or []):
            if not record.get('file_id'):
                continue
            file_id=str(record['file_id'])
            object_path = (record.get('object_name') or record.get('path_or_url')
                           or (uploaded_paths[position] if position < len(uploaded_paths) else None))
            query = {'file_id': file_id, 'scope': 'full'}
            if object_path:
                # A newly uploaded file may not yet have a durable lifecycle
                # row. The product needs the object path in that case.
                query['path_or_url'] = str(object_path)
            register_asset('knowledge_files',file_id,file_id,owner_case_id='KB-FILE-PREP',cleanup={
                'service':'config','identity':identity.id,'method':'DELETE',
                'path':f'/indices/{index_name}/documents?'+urlencode(query),
                'allowed_statuses':[200,404]})
    else:
        paths=list(payload.get('uploaded_file_paths') or [])
        for record in payload.get('results') or []:
            if record.get('success'):
                name=record.get('object_name') or record.get('path') or record.get('file_path')
                if name:paths.append(name)
        for name in dict.fromkeys(paths):
            register_asset('owned_attachments',str(name),str(name),owner_case_id='ATTACHMENT-PREP',cleanup={
                'service':'config','identity':identity.id,'method':'DELETE',
                'path':f'/file/storage/{quote(str(name),safe="/")}', 'allowed_statuses':[200,404]})


async def _upload_kb_file(identity, index_name: str, asset_key: str = "basic_text") -> dict:
    upload = _upload_tuple("files", asset_key, content_type="text/plain")
    async with client("config", token=identity.access_token) as api:
        response = await api.post(
            "/file/upload",
            data={"destination": "minio", "folder": "knowledge_base", "index_name": index_name},
            files=[("file", upload)],
        )
    if response.status_code in (200,207):
        register_uploaded_files(identity,response.json(),index_name=index_name)
    assert_status(response, 200)
    payload = response.json()
    assert payload.get("uploaded_file_paths") and payload.get("file_records")
    record = payload["file_records"][0]
    assert record.get("file_id") and record.get("status") in {"UPLOADED", "PROCESSING", "COMPLETED"}
    return {"payload": payload, "record": record, "object_name": _object_name(payload)}


async def _upload_attachment(identity, asset_key: str = "basic_text", content_type: str = "text/plain") -> str:
    upload = _upload_tuple("files", asset_key, content_type=content_type)
    return await upload_attachment_bytes(identity,*upload)


async def upload_attachment_bytes(identity,filename: str,content: bytes,content_type: str) -> str:
    """Upload deterministic generated fixture bytes and journal actual returned keys."""
    upload=(filename,content,content_type)
    async with client("runtime", token=identity.access_token) as api:
        response = await api.post("/file/storage", data={"folder": "attachments"}, files=[("files", upload)])
    if response.status_code in (200,207):
        register_uploaded_files(identity,response.json())
    assert_status(response, 200)
    payload=response.json()
    return _object_name(payload)


async def _remove_object(identity, object_name: str) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/file/storage/{quote(object_name, safe='/')}")
    assert_status(response, (200, 404))
