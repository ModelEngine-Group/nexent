# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the platform creator definition identified by a signed AgentOS request."""

from sqlalchemy import text

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.rdb.client import get_db_session


def read_system_creator(agent_id: int, version_no: int, system_key: str) -> dict | None:
    query = text("""
        SELECT agent_id, version_no, name, description, max_steps, enable_protocol_repair_retry
        FROM nexent.ag_tenant_agent_t
        WHERE agent_id = :agent_id AND version_no = :version_no
          AND tenant_id = :tenant_id AND system_key = :system_key
          AND agent_origin = 'SYSTEM' AND delete_flag = 'N' AND enabled IS NOT FALSE
    """)
    with get_db_session() as session:
        row = session.execute(query, {
            "agent_id": agent_id, "version_no": version_no,
            "tenant_id": ASSET_OWNER_TENANT_ID, "system_key": system_key,
        }).mappings().first()
        return dict(row) if row is not None else None
