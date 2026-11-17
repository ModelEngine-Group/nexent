# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real public routers with controlled external identity and source-upload boundaries."""

from types import SimpleNamespace

import httpx
import sqlalchemy as sa


def observe_requests(app):
    paths = []

    @app.middleware("http")
    async def observe(request, call_next):
        paths.append(request.url.path)
        return await call_next(request)

    return paths


def install_public_ingestion(app, engine, monkeypatch, tmp_path):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "UPLOAD_FOLDER", str(tmp_path))
    from contracts.file import UploadFilesResult
    from management.api import northbound
    from management.api.file import file_management

    from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle

    monkeypatch.setattr(
        file_management,
        "get_current_user_id",
        lambda authorization: ("user-a", "tenant-a"),
    )
    monkeypatch.setattr(
        file_management, "require_knowledge_base_edit_permission", lambda *args: None
    )

    async def identity(request):
        return SimpleNamespace(user_id="user-a", tenant_id="tenant-a")

    async def uploaded(*args, **kwargs):
        table = KnowledgeFileLifecycle.__table__
        with engine.connect() as connection:
            row = (
                connection.execute(sa.select(table).where(table.c.file_id == "b" * 32))
                .mappings()
                .one()
            )
        return UploadFilesResult(
            [],
            [row["source_key"]],
            [row["original_filename"]],
            file_records=[
                {
                    "file_id": row["file_id"],
                    "object_name": row["source_key"],
                }
            ],
        )

    monkeypatch.setattr(northbound, "_require_asset_owner_context", identity)
    monkeypatch.setattr(northbound, "upload_files_impl", uploaded)
    app.include_router(file_management.file_management_config_router)
    app.include_router(northbound.router)


async def admit_through_public_interfaces(url, value):
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        first = await client.post(
            url + "/api/file/process",
            json={
                "files": [
                    {
                        "file_id": value.file_id,
                        "path_or_url": value.source.key,
                        "filename": value.filename,
                    }
                ],
                "index_name": "kb-one",
                "destination": "minio",
                "chunking_strategy": "basic",
            },
        )
        assert first.status_code == 201, first.text
        payload = first.json()
        assert set(payload) == {"message", "process_tasks"}
        assert payload["message"] == "Files processing triggered successfully"
        assert set(payload["process_tasks"]) == {"task_id"}
        replay = await client.post(
            url + "/api/nb/v1/knowledge/file/upload",
            data={"index_name": "kb-one"},
            files={"file": (value.filename, b"controlled upload")},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json() == {
            "message": "Files uploaded and processing triggered successfully",
            "uploaded_filenames": [value.filename],
            "uploaded_file_paths": [value.source.key],
            "errors": [],
            "process_tasks": payload["process_tasks"],
        }
        return payload["process_tasks"]["task_id"]
