"""Authorization boundary for changes to external Agent relationships."""

from consts.exceptions import AgentNotFoundError, ForbiddenError
from database.agent_db import is_system_agent
from services.agent_draft_permission_service import AgentDraftEditError, require_agent_draft_edit


def require_external_relation_edit(local_agent_id: int, tenant_id: str, user_id: str) -> None:
    """Require a tenant-owned, editable ordinary parent before relationship writes."""
    try:
        require_agent_draft_edit(agent_id=local_agent_id, tenant_id=tenant_id, user_id=user_id)
    except AgentDraftEditError as exc:
        if exc.code == "agent_read_only":
            raise ForbiddenError("You do not have permission to edit this agent") from exc
        raise AgentNotFoundError("agent not found") from exc
    if is_system_agent(local_agent_id, tenant_id) is True:
        raise ForbiddenError("System Agent is managed by the platform")
