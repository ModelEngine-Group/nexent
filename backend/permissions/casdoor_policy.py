# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve opt-in Casdoor feature grants for the frontend and API guards."""

import time

from consts import const as settings

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
SNAPSHOT_KEY = "casdoor_feature_grants"
SNAPSHOT_TTL_SECONDS = 60
_MANAGED_ROLES = {"USER", "DEV", "ADMIN"}


def policy_scope() -> str | None:
    model = settings.CASDOOR_PERMISSION_MODEL
    if model and "/" not in model and settings.is_casdoor_role_sync_configured():
        return f"{settings.CASDOOR_ENDPOINT}|{settings.CASDOOR_ROLE_SYNC_ORGANIZATION}/{model}"
    return None


def make_snapshot(role: str, grants: set[str], observed_at: float) -> dict:
    return {"scope": policy_scope(), "role": role, "grants": sorted(grants & FEATURE_ACTIONS), "at": observed_at}


def managed_grants(metadata: object, role: str, *, now: float | None = None) -> set[str] | None:
    """Return None for local policy, or the current grants for a managed account."""
    scope = policy_scope()
    if not scope or role not in _MANAGED_ROLES or not isinstance(metadata, dict) or metadata.get("auth_provider") != "casdoor":
        return None
    snapshot = metadata.get(SNAPSHOT_KEY)
    if not isinstance(snapshot, dict) or snapshot.get("scope") != scope or snapshot.get("role") != role:
        return set()
    checked_at = snapshot.get("at")
    grants = snapshot.get("grants")
    if type(checked_at) not in (int, float) or not isinstance(grants, list):
        return set()
    age = (time.time() if now is None else now) - checked_at
    if not 0 <= age < SNAPSHOT_TTL_SECONDS:
        return set()
    return {grant for grant in grants if isinstance(grant, str) and grant in FEATURE_ACTIONS}


def feature_grants(user_id: str, role: str) -> set[str] | None:
    if role not in _MANAGED_ROLES or not policy_scope():
        return None
    from management.db.identity.account import get_account

    account = get_account(user_id)
    return managed_grants(account.get("source_metadata") if account else None, role)


def permission_override(user_id: str, role: str, action: str) -> bool | None:
    grants = feature_grants(user_id, role) if action in FEATURE_ACTIONS else None
    return None if grants is None else action in grants


def overlay_user_permissions(data: dict, grants: set[str]) -> None:
    """Use the same snapshot for visible actions and the managed menu entries."""
    data["permissions"] = sorted((set(data["permissions"]) - FEATURE_ACTIONS) | grants)
    routes = [route for route in data["accessibleRoutes"] if route not in {"/skill-space", "/models"}]
    if grants & {SKILL_READ, SKILL_PUBLISH, SKILL_REVIEW} or "skill:create" in data["permissions"]:
        routes.extend(["/resource-space", "/skill-space"])
    if {"menu:models", "model:read"} <= grants:
        routes.extend(["/agent-dev", "/models"])
    data["accessibleRoutes"] = list(dict.fromkeys(routes))
