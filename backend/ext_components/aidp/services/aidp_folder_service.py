# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP folder-tree, folder CRUD and folder-file operation services."""

from __future__ import annotations

from typing import Any, Dict, List

from ext_components.aidp.services.aidp_client import (
    _get_aidp_folder_level,
    _get_folders_path,
    _get_knowledge_files_path,
    _join_folder_path,
    _request_aidp_json,
    _resolve_aidp_folder_id,
)
from ext_components.aidp.services.aidp_service import (
    _extract_doc_status,
    _normalize_aidp_doc,
)


def _normalize_folder_tree_file(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a folder-tree file without inventing a creation time.

    ``_normalize_aidp_doc`` falls back to ``update_time`` for rows that only
    report an update timestamp, which is right for the legacy file list but
    wrong for the new "created at" column. Folder/Files only guarantees a
    creation time when one of its explicit fields is present; otherwise the
    UI must render an unknown value rather than relabel the update time.

    Folder/Files reports the processing status under an alias (usually
    ``file_status``); re-emit it under the canonical ``status`` key so the
    file list can render the status column from one field.
    """
    normalized = _normalize_aidp_doc(raw)
    has_creation_source = any(
        raw.get(key) not in (None, "", False)
        for key in ("first_upload_time", "create_time", "created_at")
    )
    if not has_creation_source:
        normalized["created_at"] = None
    status = _extract_doc_status(raw)
    if status is None:
        normalized.pop("status", None)
    else:
        normalized["status"] = status
    return normalized


def get_aidp_folder_tree_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    folder_path: str,
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    include_files: bool = True,
) -> Dict[str, Any]:
    """Read one level of the new AIDP folder tree.

    The route is addressed by numeric FolderId; the public Nexent API keeps
    path addressing and resolves the id here. File rows are only returned when
    ``include_files`` is true, which the new AIDP API defaults to false.
    """
    folder_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, folder_path)
    result = _get_aidp_folder_level(
        server_url,
        api_key,
        kds_id,
        folder_id,
        folder_path,
        include_files=include_files,
        page=page,
        page_size=page_size,
        keyword=keyword,
        file_type=file_type,
        file_status=file_status,
    )

    folders = result.get("folders")
    result["folders"] = [
        folder for folder in folders if isinstance(folder, dict)
    ] if isinstance(folders, list) else []

    files = result.get("files") if isinstance(result.get("files"), dict) else {}
    value = files.get("value")
    files["value"] = [
        _normalize_folder_tree_file(item) if isinstance(item, dict) else item
        for item in value
    ] if isinstance(value, list) else []
    files["page"] = int(files.get("page") or page)
    files["page_size"] = int(files.get("page_size") or page_size)
    files["total"] = int(files.get("total") or 0)
    result["files"] = files
    result["folder_path"] = str(result.get("folder_path") or folder_path)
    result["folder_id"] = int(result.get("folder_id") or folder_id)
    return result


def create_aidp_folder_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    parent_folder: str,
    folder_name: str,
) -> Dict[str, Any]:
    """Create one folder below a parent folder addressed by its new FolderId."""
    parent_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, parent_folder)
    return _request_aidp_json(
        server_url,
        api_key,
        "POST",
        f"{_get_folders_path(kds_id)}/{parent_id}",
        context=f"create-folder:{kds_id}",
        json_body={
            "parent_folder_path": parent_folder,
            "folder_name": folder_name,
        },
    )


def rename_aidp_folder_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    parent_folder: str,
    old_folder_name: str,
    new_folder_name: str,
) -> Dict[str, Any]:
    """Rename one folder addressed by its own FolderId."""
    source_path = _join_folder_path(parent_folder, old_folder_name)
    folder_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, source_path)
    return _request_aidp_json(
        server_url,
        api_key,
        "PATCH",
        f"{_get_folders_path(kds_id)}/{folder_id}",
        context=f"rename-folder:{kds_id}",
        json_body={
            "parent_folder_path": parent_folder,
            "old_folder_name": old_folder_name,
            "new_folder_name": new_folder_name,
        },
    )


def delete_aidp_folder_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    folder_path: str,
) -> None:
    """Delete one empty folder addressed by its own FolderId."""
    folder_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, folder_path)
    _request_aidp_json(
        server_url,
        api_key,
        "DELETE",
        f"{_get_folders_path(kds_id)}/{folder_id}",
        context=f"delete-folder:{kds_id}",
        params={"folder_path": folder_path},
    )


def move_aidp_folder_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    parent_folder: str,
    folder_name: str,
    target_folder: str,
) -> Dict[str, Any]:
    """Move one folder below a target folder using the new target_* fields."""
    source_path = _join_folder_path(parent_folder, folder_name)
    folder_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, source_path)
    target_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, target_folder)
    return _request_aidp_json(
        server_url,
        api_key,
        "POST",
        f"{_get_folders_path(kds_id)}/{folder_id}/Move",
        context=f"move-folder:{kds_id}",
        json_body={
            "src_parent_folder_path": parent_folder,
            "folder_name": folder_name,
            "target_parent_folder_path": target_folder,
            "target_parent_folder_id": target_id,
            "merge_on_conflict": False,
        },
    )


def move_aidp_files_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuids: List[str],
    target_folder: str,
) -> Dict[str, Any]:
    """Move knowledge files using folder id + path and per-file outcomes."""
    target_id = _resolve_aidp_folder_id(server_url, api_key, kds_id, target_folder)
    return _request_aidp_json(
        server_url,
        api_key,
        "POST",
        f"{_get_knowledge_files_path(kds_id)}/Move",
        context=f"move-files:{kds_id}",
        json_body={
            "file_uuids": file_uuids,
            "target_folder_path": target_folder,
            "target_folder_id": target_id,
        },
    )


def rename_aidp_file_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
    new_file_name: str,
) -> Dict[str, Any]:
    """Rename one knowledge file; the new AIDP contract returns 204."""
    return _request_aidp_json(
        server_url,
        api_key,
        "PATCH",
        _get_knowledge_files_path(kds_id),
        context=f"rename-file:{kds_id}",
        json_body={
            "file_uuid": file_uuid,
            "new_file_name": new_file_name,
        },
    )

