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
from ext_components.aidp.services.aidp_client import set_aidp_accept_language


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
    set_aidp_accept_language(request.headers.get("accept-language"))
    return user_id, tenant_id


def _credentials() -> tuple[str, str]:
    return AIDP_SERVER_URL, AIDP_API_KEY


def _validate_folder_path(value: str, *, allow_root: bool = True) -> str:
    """Validate a knowledge-base-relative folder path.

    The AIDP API addresses folders by numeric FolderId; the path travels as a
    query/body attribute. Rejecting malformed input here keeps a bad path from
    being forwarded as an opaque upstream error.
    """
    if not value.startswith("/"):
        raise ValueError("folder_path must start with '/'")
    if "\\" in value or "//" in value:
        raise ValueError("folder_path contains an invalid separator")
    if ".." in value.split("/"):
        raise ValueError("folder_path must not contain '..'")
    if value == "/":
        if not allow_root:
            raise ValueError("the root folder cannot be used here")
        return "/"
    return value.rstrip("/")


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


def _validate_folder_name(value: str) -> str:
    """Reject the two traversal names left after the type-level pattern."""
    if value in {".", ".."}:
        raise ValueError("folder_name is invalid")
    return value


def _validate_non_root_folder_path(value: str) -> str:
    return _validate_folder_path(value, allow_root=False)


FolderPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    AfterValidator(_validate_folder_path),
]
NonRootFolderPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    AfterValidator(_validate_non_root_folder_path),
]
FolderName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_FOLDER_NAME_MAX_LENGTH,
        pattern=r"^[^/\\]+$",
    ),
    AfterValidator(_validate_folder_name),
]
FileName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_FOLDER_NAME_MAX_LENGTH,
        pattern=r"^[^/\\]+$",
    ),
]
