# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the saved inference overrides on an authorized Agent version."""

from sqlalchemy import text

from contracts.constants.constants import ASSET_OWNER_TENANT_ID


def read_agent_model_overrides(agent_id: int, version_no: int, tenant_id: str) -> dict | None:
    from infrastructure.rdb.client import get_db_session

    query = text("""
        SELECT model_params_override
        FROM nexent.ag_tenant_agent_t
        WHERE agent_id = :agent_id AND version_no = :version_no
          AND tenant_id IN (:tenant_id, :platform_tenant_id)
          AND delete_flag <> 'Y'
    """)
    with get_db_session() as session:
        result = session.execute(query, {
            "agent_id": agent_id, "version_no": version_no, "tenant_id": tenant_id,
            "platform_tenant_id": ASSET_OWNER_TENANT_ID,
        }).scalar_one_or_none()
    return result if isinstance(result, dict) else None
