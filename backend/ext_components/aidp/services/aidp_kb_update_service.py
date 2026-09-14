"""Save local KB permissions before optionally synchronizing changed metadata."""

import logging

from consts.exceptions import AppException
from ext_components.aidp.consts.aidp_exceptions import AidpKbNotFoundError
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_access_service import (
    invalidate_aidp_catalog_cache,
    invalidate_aidp_kb_detail_cache,
)
from ext_components.aidp.services.aidp_service import update_aidp_kb_impl

logger = logging.getLogger(__name__)


def save_kb_settings(
    *, kb_id: str, tenant_id: str, user_id: str, ingroup_permission: str,
    group_ids: list[int], metadata: dict, server_url: str, api_key: str,
) -> dict:
    """Commit permissions first; metadata contains only explicitly changed fields."""
    if not perms.update_permission(
        kb_id=kb_id, tenant_id=tenant_id, ingroup_permission=ingroup_permission,
        group_ids=group_ids, updated_by=user_id,
    ):
        raise AidpKbNotFoundError(kb_id)

    result = {"success": True, "permissions_saved": True, "metadata_status": "unchanged"}
    if not metadata:
        return result

    try:
        updated = update_aidp_kb_impl(server_url, api_key, kb_id, metadata)
    except AppException:
        logger.exception("AIDP metadata update failed after permissions were saved for %s", kb_id)
        return {**result, "success": False, "metadata_status": "failed"}
    finally:
        invalidate_aidp_catalog_cache(server_url, api_key)
        invalidate_aidp_kb_detail_cache(server_url, api_key, kb_id)

    new_name = updated.get("kds_name") or metadata.get("name")
    if new_name:
        perms.update_permission(
            kb_id=kb_id, tenant_id=tenant_id, kds_name=new_name, updated_by=user_id,
        )
    return {**result, "metadata_status": "updated", "metadata": updated}
