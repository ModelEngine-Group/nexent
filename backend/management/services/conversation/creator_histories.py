# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read owned creator histories for one tenant resource, independently of entrypoint."""

from management.db.agent.repository import query_agent_records_for_nl2agent
from management.db.conversation.repository import get_conversation_list_page
from management.db.skill.repository import get_skill_by_id
from management.services.agent.system import system_agent_provider


def list_creator_histories(*, kind: str, target_id: int, user_id: str, tenant_id: str,
                           offset: int = 0, limit: int = 20) -> dict:
    if kind not in ("agent", "skill") or target_id < 1 or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid creator history query")
    if not user_id or not tenant_id:
        raise PermissionError("Authenticated user and tenant are required")
    # Viewing one's own transcript does not grant edit permission; continuation checks it separately.
    if kind == "agent":
        accessible = any(row.get("version_no") == 0 and row.get("delete_flag") == "N"
                         for row in query_agent_records_for_nl2agent(target_id, tenant_id))
    else:
        accessible = get_skill_by_id(target_id, tenant_id) is not None
    if not accessible:
        raise PermissionError("Creator target is not accessible in this tenant")
    executor = system_agent_provider.get_creator_ref(tenant_id, f"nl2{kind}_main")
    page = get_conversation_list_page(
        user_id=user_id, today_start_ms=0, week_start_ms=0, offset=offset, limit=limit,
        creator_agent_id=executor.agent_id, creator_target={"type": kind, "id": target_id},
    )
    return {"items": page["items"], "total": page["metadata"]["total"]}
