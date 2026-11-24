# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP folder-tree and folder/file-operation routes.

These routes were split out of the legacy management router so the directory
feature has one focused surface. The public paths and request/response bodies
remain unchanged.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ext_components.aidp.apps.aidp_mgmt_common import (
    _auth,
    _credentials,
    _normalize_folder_name,
    _normalize_folder_path,
)
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_folder_service import (
    create_aidp_folder_impl,
    delete_aidp_folder_impl,
    get_aidp_folder_tree_impl,
    move_aidp_files_impl,
    move_aidp_folder_impl,
    rename_aidp_file_impl,
    rename_aidp_folder_impl,
)


aidp_folder_router = APIRouter()


class CreateAidpFolderRequest(BaseModel):
    """Create one folder under an existing parent folder."""

    model_config = ConfigDict(extra="forbid")

    parent_folder: str = Field(..., description="Parent folder path; root is '/'")
    folder_name: str = Field(..., min_length=1, description="New folder name")

    @field_validator("parent_folder")
    @classmethod
    def _validate_parent(cls, value: str) -> str:
        return _normalize_folder_path(value)

    @field_validator("folder_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_folder_name(value)


class RenameAidpFolderRequest(BaseModel):
    """Rename one folder inside its current parent."""

    model_config = ConfigDict(extra="forbid")

    parent_folder: str = Field(..., description="Parent folder path; root is '/'")
    old_folder_name: str = Field(..., min_length=1)
    new_folder_name: str = Field(..., min_length=1)

    @field_validator("parent_folder")
    @classmethod
    def _validate_parent(cls, value: str) -> str:
        return _normalize_folder_path(value)

    @field_validator("old_folder_name", "new_folder_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_folder_name(value)


class MoveAidpFolderRequest(BaseModel):
    """Move one folder under another folder."""

    model_config = ConfigDict(extra="forbid")

    parent_folder: str = Field(..., description="Current parent folder path")
    folder_name: str = Field(..., min_length=1)
    target_folder: str = Field(..., description="Destination parent folder path")
    merge_on_conflict: bool = Field(
        False,
        description="Merge into an existing same-named folder instead of failing",
    )

    @field_validator("parent_folder", "target_folder")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalize_folder_path(value)

    @field_validator("folder_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_folder_name(value)

    @model_validator(mode="after")
    def _reject_self_move(self) -> "MoveAidpFolderRequest":
        parent_prefix = "" if self.parent_folder == "/" else self.parent_folder
        source_path = f"{parent_prefix}/{self.folder_name}"
        if self.target_folder == source_path or self.target_folder.startswith(
            f"{source_path}/"
        ):
            raise ValueError("a folder cannot be moved into itself or its subfolder")
        return self


class MoveAidpFilesRequest(BaseModel):
    """Move one or more knowledge files into a folder."""

    model_config = ConfigDict(extra="forbid")

    file_uuids: List[UUID] = Field(..., min_length=1)
    target_folder: str = Field(..., description="Destination folder path")

    @field_validator("target_folder")
    @classmethod
    def _validate_target(cls, value: str) -> str:
        return _normalize_folder_path(value)


class RenameAidpFileRequest(BaseModel):
    """Rename one knowledge file."""

    model_config = ConfigDict(extra="forbid")

    file_uuid: UUID = Field(..., description="AIDP file UUID")
    new_file_name: str = Field(..., min_length=1, description="New file name")

    @field_validator("new_file_name")
    @classmethod
    def _validate_file_name(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("new_file_name is required")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("new_file_name must not contain a path separator")
        if len(normalized) > 255:
            raise ValueError("new_file_name must be at most 255 characters")
        return normalized


@aidp_folder_router.get("/knowledge-bases/{kds_id}/folders/tree")
async def get_folder_tree(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    folder_path: Annotated[
        str, Query(description="Folder path; root is '/'")
    ] = "/",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 10,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
    file_type: Annotated[str | None, Query(max_length=32)] = None,
    file_status: Annotated[str | None, Query(max_length=32)] = None,
    include_files: Annotated[
        bool, Query(description="Include current folder files")
    ] = True,
) -> JSONResponse:
    """Read one folder level: direct subfolders plus its paginated files."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    try:
        normalized_path = _normalize_folder_path(folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-folder-tree",
        get_aidp_folder_tree_impl,
        server_url,
        api_key,
        kds_id,
        normalized_path,
        page,
        page_size,
        keyword,
        file_type,
        file_status,
        include_files,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_folder_router.post("/knowledge-bases/{kds_id}/folders")
async def create_folder(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: CreateAidpFolderRequest,
) -> JSONResponse:
    """Create one folder below an existing folder."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-create-folder",
        create_aidp_folder_impl,
        server_url,
        api_key,
        kds_id,
        body.parent_folder,
        body.folder_name,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_folder_router.patch("/knowledge-bases/{kds_id}/folders")
async def rename_folder(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: RenameAidpFolderRequest,
) -> JSONResponse:
    """Rename one folder within its current parent."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-rename-folder",
        rename_aidp_folder_impl,
        server_url,
        api_key,
        kds_id,
        body.parent_folder,
        body.old_folder_name,
        body.new_folder_name,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_folder_router.delete("/knowledge-bases/{kds_id}/folders")
async def delete_folder(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    folder_path: Annotated[str, Query(description="Folder path to delete")],
) -> Response:
    """Delete one empty folder; AIDP rejects non-empty folders."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    try:
        normalized_path = _normalize_folder_path(folder_path, allow_root=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    server_url, api_key = _credentials()
    await run_blocking(
        "aidp-delete-folder",
        delete_aidp_folder_impl,
        server_url,
        api_key,
        kds_id,
        normalized_path,
        lane="control-io",
        owner="config",
    )
    return Response(status_code=HTTPStatus.NO_CONTENT)


@aidp_folder_router.post("/knowledge-bases/{kds_id}/folders/move")
async def move_folder(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: MoveAidpFolderRequest,
) -> JSONResponse:
    """Move one folder below another folder."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-move-folder",
        move_aidp_folder_impl,
        server_url,
        api_key,
        kds_id,
        body.parent_folder,
        body.folder_name,
        body.target_folder,
        body.merge_on_conflict,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_folder_router.post("/knowledge-bases/{kds_id}/files/move")
async def move_files(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: MoveAidpFilesRequest,
) -> JSONResponse:
    """Move knowledge files to a folder; AIDP reports per-file outcomes."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-move-files",
        move_aidp_files_impl,
        server_url,
        api_key,
        kds_id,
        [file_uuid.hex for file_uuid in body.file_uuids],
        body.target_folder,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_folder_router.patch("/knowledge-bases/{kds_id}/files")
async def rename_file(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: RenameAidpFileRequest,
) -> JSONResponse:
    """Rename one knowledge file."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-rename-file",
        rename_aidp_file_impl,
        server_url,
        api_key,
        kds_id,
        body.file_uuid.hex,
        body.new_file_name,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
