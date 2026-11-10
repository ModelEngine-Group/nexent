# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Object-read scope shared by Management and Runtime tool adapters."""

from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX, ASSET_OWNER_TENANT_ID
from nexent.multi_modal.utils import parse_s3_url


def can_read_object(object_name: str, user_id: str, tenant_id: str | None) -> bool:
    if not user_id:
        return False
    if object_name.startswith(ASSET_OWNER_ATTACHMENTS_PREFIX):
        return tenant_id == ASSET_OWNER_TENANT_ID
    if object_name.startswith(("knowledge_base/", "images_in_attachments/")):
        return True
    if object_name.startswith("workspace/"):
        parts = object_name.split("/")
        return len(parts) >= 5 and parts[1] == user_id and parts[3] == "outputs"
    if object_name.startswith((f"attachments/{user_id}/", f"skill-files/{user_id}/")):
        return True
    return object_name.startswith("attachments/") and "/" not in object_name.removeprefix("attachments/")


def require_s3_read_access(urls: list[str], user_id: str, tenant_id: str) -> None:
    for url in urls:
        try:
            _, object_name = parse_s3_url(url)
        except ValueError as exc:
            raise PermissionError("Invalid S3 URL") from exc
        if not can_read_object(object_name, user_id, tenant_id):
            raise PermissionError("Object is outside the run's read scope")
