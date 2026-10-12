"""Own the temporary AIDP permission rows used by one auth-surface case."""
from __future__ import annotations

import re

from ext_components.aidp.database import aidp_permission_db
from shared.asset_registry import register_asset


def create_owned_permission(*, kb_id, owner_user_id, tenant_id, group_ids, ingroup_permission):
    if not re.fullmatch(r'kb-(?:private|shared)-[a-f0-9]{12}', kb_id):
        raise ValueError('refusing to create an unscoped AIDP test permission')
    row_id = aidp_permission_db.create_permission(
        kb_id=kb_id, kds_name=kb_id, owner_user_id=owner_user_id,
        tenant_id=tenant_id, ingroup_permission=ingroup_permission,
        group_ids=group_ids, resource_status='ACTIVE', created_by=owner_user_id,
    )
    try:
        register_asset(
            'owned_aidp_permissions', kb_id, row_id,
            owner_case_id='API-AUTO-3B8A8FB947806F0E',
            cleanup={'kind': 'delete_owned_aidp_permission', 'kb_id': kb_id,
                     'row_id': row_id, 'tenant_id': tenant_id,
                     'owner_user_id': owner_user_id},
        )
    except BaseException:
        aidp_permission_db.soft_delete_permission(
            kb_id=kb_id, tenant_id=tenant_id, updated_by=owner_user_id,
        )
        raise
    return row_id


def delete_owned_permission(*, kb_id, row_id, tenant_id, owner_user_id):
    if not re.fullmatch(r'kb-(?:private|shared)-[a-f0-9]{12}', kb_id):
        raise ValueError('refusing to delete an unscoped AIDP test permission')
    row = aidp_permission_db.get_permission_by_kb_id(kb_id, tenant_id)
    if row is None:  # The target case already cleaned up its exact row.
        return
    if (int(row['id']) != int(row_id) or row['owner_user_id'] != owner_user_id
            or row['kds_name'] != kb_id or row['tenant_id'] != tenant_id):
        raise RuntimeError('AIDP permission ownership mismatch; refusing cleanup')
    if not aidp_permission_db.soft_delete_permission(
        kb_id=kb_id, tenant_id=tenant_id, updated_by=owner_user_id,
    ):
        raise RuntimeError('owned AIDP permission cleanup did not delete a row')
