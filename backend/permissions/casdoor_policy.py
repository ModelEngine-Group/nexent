# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve opt-in Casdoor feature grants for the frontend and API guards."""

import time

from consts import const as settings
from contracts.constants import environment
from contracts.roles import primary_role

SKILL_READ = "skill.repository:read"
SKILL_INSTALL = "skill.repository:install"
SKILL_PUBLISH = "skill.repository:publish"
SKILL_REVIEW = "skill.repository:review"
FEATURE_RESOURCE_ACTIONS = {
    "nexent:skill-repository": (SKILL_READ, SKILL_INSTALL, SKILL_PUBLISH, SKILL_REVIEW),
    "nexent:model": ("model:read", "model:create", "model:update", "model:delete", "menu:models"),
    "nexent:knowledge-base": ("kb.capacity:read", "kb.capacity:manage"),
    "nexent:tag-library": ("tag_library:manage",),
    "nexent:dreaming": ("dreaming:view_tenant", "dreaming:edit_tenant"),
}
FEATURE_ACTION_RESOURCES = {
    action: resource for resource, actions in FEATURE_RESOURCE_ACTIONS.items() for action in actions
}
FEATURE_ACTIONS = frozenset(FEATURE_ACTION_RESOURCES)
STAGED_ACTION_RESOURCES = {
    "kb:create": "nexent:knowledge-base",
    "kb:update": "nexent:knowledge-base",
    "kb:delete": "nexent:knowledge-base",
}
SNAPSHOT_KEY = "casdoor_feature_grants"
SNAPSHOT_TTL_SECONDS = 60
_MANAGED_ROLES = {"USER", "DEV", "ADMIN"}


def staged_actions() -> frozenset[str]:
    configured = environment.CASDOOR_ADDITIONAL_MANAGED_ACTIONS
    if configured - STAGED_ACTION_RESOURCES.keys():
        raise ValueError("CASDOOR_ADDITIONAL_MANAGED_ACTIONS contains an unsupported action")
    return configured


def managed_action_resources() -> dict[str, str]:
    return FEATURE_ACTION_RESOURCES | {action: STAGED_ACTION_RESOURCES[action] for action in staged_actions()}


def policy_scope() -> str | None:
    model = settings.CASDOOR_PERMISSION_MODEL
    if model and "/" not in model and settings.is_casdoor_role_sync_configured():
        scope = f"{settings.CASDOOR_ENDPOINT}|{settings.CASDOOR_ROLE_SYNC_ORGANIZATION}/{model}"
        additional = staged_actions()
        return f"{scope}|{','.join(sorted(additional))}" if additional else scope
    return None


def make_snapshot(role: str, grants: set[str], observed_at: float, *, subject: str) -> dict:
    return {"scope": policy_scope(), "role": role, "subject": subject,
            "grants": sorted(grants & managed_action_resources().keys()), "at": observed_at}


def managed_grants(metadata: object, role: str, *, subject: str | None, now: float | None = None) -> set[str] | None:
    """Return None for local policy, or the current grants for a managed account."""
    scope = policy_scope()
    metadata = metadata if isinstance(metadata, dict) else {}
    if not scope or role not in _MANAGED_ROLES or (not subject and metadata.get("auth_provider") != "casdoor"):
        return None
    snapshot = metadata.get(SNAPSHOT_KEY)
    if (not subject or not isinstance(snapshot, dict) or snapshot.get("scope") != scope
            or snapshot.get("role") != role or snapshot.get("subject") != subject):
        return set()
    checked_at = snapshot.get("at")
    grants = snapshot.get("grants")
    if type(checked_at) not in (int, float) or not isinstance(grants, list):
        return set()
    age = (time.time() if now is None else now) - checked_at
    if not 0 <= age < SNAPSHOT_TTL_SECONDS:
        return set()
    resources = managed_action_resources()
    return {grant for grant in grants if isinstance(grant, str) and grant in resources}


def feature_grants(user_id: str, role: str | tuple[str, ...]) -> set[str] | None:
    if not isinstance(role, str):
        if not role:
            return None
        role = primary_role(role)
    if role not in _MANAGED_ROLES or not policy_scope():
        return None
    from management.db.identity.account import get_account
    from management.db.identity.oauth_account import get_casdoor_binding_subject

    account = get_account(user_id)
    if not account:
        return None
    return managed_grants(account.get("source_metadata"), role, subject=get_casdoor_binding_subject(user_id))


def permission_override(user_id: str, role: str | tuple[str, ...], action: str) -> bool | None:
    grants = feature_grants(user_id, role) if action in managed_action_resources() else None
    return None if grants is None else action in grants


def overlay_user_permissions(data: dict, grants: set[str]) -> None:
    """Use the same snapshot for visible actions and the managed menu entries."""
    data["permissions"] = sorted((set(data["permissions"]) - managed_action_resources().keys()) | grants)
    routes = [route for route in data["accessibleRoutes"] if route not in {"/skill-space", "/models"}]
    if grants & {SKILL_READ, SKILL_PUBLISH, SKILL_REVIEW} or "skill:create" in data["permissions"]:
        routes.extend(["/resource-space", "/skill-space"])
    if {"menu:models", "model:read"} <= grants:
        routes.extend(["/agent-dev", "/models"])
    data["accessibleRoutes"] = list(dict.fromkeys(routes))
