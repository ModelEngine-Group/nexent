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


def read_schedule(actor, tenant_id=None):
    tenant = tenant_id or actor.tenant_id
    authorize(TrajectoryCatalog(), actor, tenant)
    try:
        return _policy(tenant, CleanupScheduleRepository().read(tenant))
    except (ValueError, TypeError) as error:
        raise QueryError("trajectory_configuration_invalid", 503) from error


def save_schedule(actor, enabled, retention_days, tenant_id=None):
    tenant = tenant_id or actor.tenant_id
    authorize(TrajectoryCatalog(), actor, tenant)
    value = CleanupPolicy(enabled=enabled, retention_days=retention_days).model_dump()
    CleanupScheduleRepository().save(tenant, value, actor.user_id)
    logger.info(
        "trajectory.cleanup_schedule_saved actor_id=%s tenant_id=%s enabled=%s retention_days=%s",
        actor.user_id,
        tenant,
        value["enabled"],
        value["retention_days"],
    )
    return _policy(tenant, value)
