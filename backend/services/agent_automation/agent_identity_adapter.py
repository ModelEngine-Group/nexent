import logging
from collections import defaultdict
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import or_, select

from consts.const import ASSET_OWNER_TENANT_ID
from database.client import get_db_session
from database.db_models import AgentInfo


AgentReference = Tuple[int, int]
logger = logging.getLogger("agent_automation.agent_identity_adapter")


def resolve_agent_display_names(
    references: Iterable[Tuple[int, Optional[int]]],
    tenant_id: str,
) -> Dict[AgentReference, str]:
    """Resolve user-facing Agent names in one query at the automation boundary."""
    normalized_references = {
        (int(agent_id), int(version_no or 0))
        for agent_id, version_no in references
        if agent_id
    }
    if not normalized_references:
        return {}

    agent_ids = {agent_id for agent_id, _ in normalized_references}
    try:
        with get_db_session() as session:
            rows = session.execute(
                select(
                    AgentInfo.agent_id,
                    AgentInfo.version_no,
                    AgentInfo.name,
                    AgentInfo.display_name,
                    AgentInfo.tenant_id,
                ).where(
                    AgentInfo.agent_id.in_(agent_ids),
                    or_(
                        AgentInfo.tenant_id == tenant_id,
                        AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
                    ),
                    AgentInfo.delete_flag != "Y",
                )
            ).all()
    except Exception:
        logger.warning("Failed to resolve Agent display names", exc_info=True)
        return {}

    candidates = defaultdict(dict)
    for row in rows:
        key = (int(row.agent_id), int(row.version_no or 0))
        current = candidates[key].get("row")
        if current is None or row.tenant_id == tenant_id:
            candidates[key]["row"] = row

    resolved: Dict[AgentReference, str] = {}
    for reference in normalized_references:
        agent_id, version_no = reference
        row = candidates.get((agent_id, version_no), {}).get("row")
        if row is None:
            row = candidates.get((agent_id, 0), {}).get("row")
        if row is None:
            available = [
                item["row"]
                for (candidate_id, _), item in candidates.items()
                if candidate_id == agent_id and item.get("row") is not None
            ]
            row = max(available, key=lambda item: int(item.version_no or 0), default=None)
        if row is not None:
            display_name = (row.display_name or row.name or "").strip()
            if display_name:
                resolved[reference] = display_name

    return resolved
