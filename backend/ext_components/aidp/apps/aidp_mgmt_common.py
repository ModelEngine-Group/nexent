# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared request/auth helpers for AIDP management routes."""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import HTTPException, Request
from pydantic import AfterValidator, Field, StringConstraints

import management.services.permission.identity.session as auth_utils_module
from contracts.constants.environment import AIDP_API_KEY, AIDP_SERVER_URL
from contracts.errors.exceptions import UnauthorizedError


_FOLDER_NAME_MAX_LENGTH = 255

# AIDP reports file_uuid in two shapes across deployments: 32-char hex
# without dashes (the 2026-11-20 contract run) and the standard 36-char UUID
# with dashes (earlier environments). Every UUID the page sends came from an
# AIDP response, so the proxy forwards it verbatim and only enforces this
# loose shape instead of normalizing through uuid.UUID (which would rewrite
# the 32-hex form and break the upstream lookup).
AIDP_FILE_UUID_PATTERN = r"^[0-9a-fA-F-]{32,36}$"
AidpFileUuid = Annotated[
    str,
    Field(
        pattern=AIDP_FILE_UUID_PATTERN,
        description="AIDP file UUID exactly as returned upstream",
    ),
]


async def _auth(request: Request) -> tuple[str, str]:
    """Resolve ``(user_id, tenant_id)`` from the Authorization header.

    Raises 401 for missing/invalid tokens or empty tenant contexts so the
    caller never has to defend against partially-authenticated state.
    """
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    try:
        user_id, tenant_id = auth_utils_module.get_current_user_id(auth)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    if not tenant_id:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="No tenant context",
        )
    return user_id, tenant_id


def _credentials() -> tuple[str, str]:
    return AIDP_SERVER_URL, AIDP_API_KEY


def _normalize_folder_path(value: str, *, allow_root: bool = True) -> str:
    """Validate a knowledge-base-relative folder path.

    The AIDP contract addresses folders by a path relative to the knowledge
    base root (``/`` for the root itself), never by id. Rejecting malformed
    input here keeps a bad path from being forwarded as an opaque upstream
    error and makes the root/name rules explicit at the HTTP boundary.
    """
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("folder_path is required")
    if not normalized.startswith("/"):
        raise ValueError("folder_path must start with '/'")
    if "\\" in normalized or "//" in normalized:
        raise ValueError("folder_path contains an invalid separator")
    if ".." in normalized.split("/"):
        raise ValueError("folder_path must not contain '..'")
    if normalized == "/":
        if not allow_root:
            raise ValueError("the root folder cannot be used here")
        return "/"
    return normalized.rstrip("/")


def _relative_path_to_directory(value: str) -> str:
    """Convert the UI's file-relative path to AIDP's directory-only field.

    The new AIDP ``relative_paths`` form field describes a directory, while
    the Nexent drawer naturally produces a file-relative path such as
    ``sub/a.md``. Drop the final filename and reject traversal segments. A
    root-level file becomes the empty string, which AIDP treats as flat inside
    the target folder.
    """
    normalized = (value or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return ""
    segments = [segment for segment in normalized.split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("relative_paths must not contain '.' or '..'")
    return "/".join(segments[:-1])


def _normalize_folder_name(value: str) -> str:
    """Validate one folder name (the path separator is never part of a name)."""
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("folder_name is required")
    if normalized in {".", ".."}:
        raise ValueError("folder_name is invalid")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("folder_name must not contain a path separator")
    if len(normalized) > _FOLDER_NAME_MAX_LENGTH:
        raise ValueError(
            f"folder_name must be at most {_FOLDER_NAME_MAX_LENGTH} characters"
        )
    return normalized


def _normalize_non_root_folder_path(value: str) -> str:
    return _normalize_folder_path(value, allow_root=False)


FolderPath = Annotated[str, AfterValidator(_normalize_folder_path)]
NonRootFolderPath = Annotated[str, AfterValidator(_normalize_non_root_folder_path)]
FolderName = Annotated[str, AfterValidator(_normalize_folder_name)]
FileName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_FOLDER_NAME_MAX_LENGTH,
        pattern=r"^[^/\\]+$",
    ),
]
