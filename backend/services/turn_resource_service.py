"""Resolve untrusted turn resource references at the authenticated boundary."""

from typing import Dict, Optional, Protocol

from nexent.core.agents.turn_resources import (
    ResolvedTurnResource,
    TurnResourceInvocation,
)

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from consts.model import TurnResourceInvocationRequest, TurnResourceReferenceRequest
from services.skill_service import SkillService


class TurnResourceResolver(Protocol):
    """Extension point for a supported resource kind."""

    resource_type: str

    def resolve(
        self,
        reference: TurnResourceReferenceRequest,
        tenant_id: str,
    ) -> ResolvedTurnResource:
        """Resolve a client reference to authoritative tenant-scoped content."""


class SkillTurnResourceResolver:
    """Resolve installed skills without trusting client-provided metadata."""

    resource_type = "skill"

    def resolve(
        self,
        reference: TurnResourceReferenceRequest,
        tenant_id: str,
    ) -> ResolvedTurnResource:
        try:
            skill_id = int(reference.resource_id)
        except (TypeError, ValueError) as exc:
            raise AppException(
                ErrorCode.COMMON_PARAMETER_INVALID,
                "Invalid skill resource ID.",
            ) from exc
        if skill_id <= 0:
            raise AppException(
                ErrorCode.COMMON_PARAMETER_INVALID,
                "Invalid skill resource ID.",
            )

        skill = SkillService(tenant_id=tenant_id).get_skill_by_id(
            skill_id=skill_id,
            tenant_id=tenant_id,
        )
        if not skill:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND,
                "The selected skill is unavailable.",
                details={"resource_type": "skill", "resource_id": str(skill_id)},
            )
        return ResolvedTurnResource(
            resource_type="skill",
            resource_id=str(skill_id),
            name=skill.get("name", ""),
            description=skill.get("description", "") or "",
            content=skill.get("content", "") or "",
        )


_RESOLVERS: Dict[str, TurnResourceResolver] = {
    SkillTurnResourceResolver.resource_type: SkillTurnResourceResolver(),
}


def resolve_turn_resources(
    request: Optional[TurnResourceInvocationRequest],
    tenant_id: str,
) -> Optional[TurnResourceInvocation]:
    """Resolve and deduplicate all resources for exactly one agent request."""
    if request is None:
        return None

    resolved = []
    seen = set()
    for reference in request.resources:
        key = (reference.resource_type, reference.resource_id)
        if key in seen:
            continue
        seen.add(key)

        resolver = _RESOLVERS.get(reference.resource_type)
        if resolver is None:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                f"Turn resource type '{reference.resource_type}' is not supported yet.",
            )
        resolved.append(resolver.resolve(reference, tenant_id))

    return TurnResourceInvocation(mode=request.mode, resources=resolved)
