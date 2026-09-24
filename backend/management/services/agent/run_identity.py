"""Identity contract for Agent resource authorization and conversation ownership."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRunIdentityContext:
    """Keep Agent resource authorization separate from conversation ownership."""

    resource_actor_user_id: str
    resource_tenant_id: str
    conversation_owner_user_id: str
    conversation_owner_tenant_id: str
    entrypoint: str
    disable_personal_memory: bool = False
