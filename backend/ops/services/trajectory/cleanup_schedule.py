# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant cleanup policy settings, restricted to authorized administrators."""

import logging

from contracts.constants import environment as config
from contracts.trajectory import CleanupPolicy
from ops.db.trajectory.catalog import TrajectoryCatalog
from ops.db.trajectory.cleanup_schedule import CleanupScheduleRepository

from .access import authorize
from .primitives import QueryError

logger = logging.getLogger(__name__)


def read_policies():
    """Let the maintenance worker retain its last value on database failure."""
    return CleanupScheduleRepository().read_all()


def _policy(tenant_id, policy):
    value = policy if policy is not None else {
        "enabled": config.TRAJECTORY_CLEANUP_ENABLED,
        "retention_days": min(config.TRAJECTORY_RETENTION_DAYS, 30),
    }
    return {
        "tenant_id": tenant_id,
        **CleanupPolicy.model_validate(value).model_dump(),
        "cleanup_time": "00:00",
        "timezone": "Asia/Shanghai",
    }


def _scope(actor, tenant_id, all_tenants):
    if all_tenants and actor.role != "SU":
        raise QueryError("administrator_required", 403)
    if all_tenants and tenant_id is not None:
        raise QueryError("invalid_parameters")
    return authorize(TrajectoryCatalog(), actor, None if all_tenants else tenant_id or actor.tenant_id)


def read_schedule(actor, tenant_id=None, all_tenants=False):
    tenants = _scope(actor, tenant_id, all_tenants)
    tenant = tenant_id or actor.tenant_id
    try:
        if all_tenants:
            policies = CleanupScheduleRepository().read_all()
            effective = [_policy(None, policies.get(target)) for target in tenants]
            mixed = bool(effective) and any(value != effective[0] for value in effective[1:])
            value = _policy(None, None) if mixed or not effective else effective[0]
            return {**value, "all_tenants": True, "mixed": mixed, "tenant_count": len(tenants)}
        return _policy(tenant, CleanupScheduleRepository().read(tenant))
    except (ValueError, TypeError) as error:
        raise QueryError("trajectory_configuration_invalid", 503) from error


def save_schedule(actor, enabled, retention_days, tenant_id=None, all_tenants=False):
    tenants = _scope(actor, tenant_id, all_tenants)
    tenant = tenant_id or actor.tenant_id
    value = CleanupPolicy(enabled=enabled, retention_days=retention_days).model_dump()
    if all_tenants:
        if not tenants:
            raise QueryError("trajectory_not_found", 404)
        CleanupScheduleRepository().save_many(tenants, value, actor.user_id)
        logger.info(
            "trajectory.cleanup_schedule_synced actor_id=%s tenant_count=%s enabled=%s retention_days=%s",
            actor.user_id, len(tenants), value["enabled"], value["retention_days"],
        )
        return {**_policy(None, value), "all_tenants": True, "mixed": False, "tenant_count": len(tenants)}
    CleanupScheduleRepository().save(tenant, value, actor.user_id)
    logger.info(
        "trajectory.cleanup_schedule_saved actor_id=%s tenant_id=%s enabled=%s retention_days=%s",
        actor.user_id,
        tenant,
        value["enabled"],
        value["retention_days"],
    )
    return _policy(tenant, value)
