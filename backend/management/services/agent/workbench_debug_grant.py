# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorize Skill mount overrides for request-owned Workbench debug runs."""

from contracts.agentos import RunSpecModel, WorkbenchDebugSkillLookup, WorkbenchSkillMounts
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches
from infrastructure.redis.client import get_redis_client

_GRANT_TTL_SECONDS = 3600


class WorkbenchDebugGrantUnavailable(RuntimeError):
    """The temporary Workbench authorization store cannot be used."""


class _WorkbenchDebugGrant(RunSpecModel):
    scope: WorkbenchDebugSkillLookup
    user_id: str
    tenant_id: str
    mounts: WorkbenchSkillMounts


def _store():
    redis = get_redis_client()
    if redis is None:
        raise WorkbenchDebugGrantUnavailable("Workbench debug scope storage is unavailable")
    return redis


def _key(run_id: str) -> str:
    return f"agentos:workbench-debug:grant:{run_id}"


def open_workbench_debug_grant(
    scope: WorkbenchDebugSkillLookup, actor: ServicePrincipal, mounts: WorkbenchSkillMounts,
) -> None:
    grant = _WorkbenchDebugGrant(scope=scope, user_id=actor.user_id, tenant_id=actor.tenant_id, mounts=mounts)
    if not _store().set(_key(scope.run_id), grant.model_dump_json(), ex=_GRANT_TTL_SECONDS, nx=True):
        raise WorkbenchDebugGrantUnavailable("Workbench debug scope already exists")


def close_workbench_debug_grant(run_id: str) -> None:
    _store().delete(_key(run_id))


def read_workbench_debug_grant(
    lookup: WorkbenchDebugSkillLookup, actor: ServicePrincipal,
) -> WorkbenchSkillMounts | None:
    raw = _store().get(_key(lookup.run_id))
    if raw is None:
        return None
    grant = _WorkbenchDebugGrant.model_validate_json(raw)
    if (grant.scope, grant.user_id, grant.tenant_id) != (lookup, actor.user_id, actor.tenant_id):
        return None
    with get_db_session() as session:
        if not tenant_membership_matches(session, actor.user_id, actor.tenant_id):
            return None
    return grant.mounts
