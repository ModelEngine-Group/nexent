# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant cleanup policy settings, restricted to authorized administrators."""

import logging

from contracts.constants import environment as config
from contracts.trajectory import CleanupScheduleRequest
from ops.db.trajectory.catalog import TrajectoryCatalog
from ops.db.trajectory.cleanup_schedule import CleanupScheduleRepository

from .access import authorize
from .primitives import QueryError

logger = logging.getLogger(__name__)


def read_intervals():
    """Let the maintenance worker retain its last value on database failure."""
    return CleanupScheduleRepository().read_all()


def _policy(tenant_id, interval):
    return {
        "tenant_id": tenant_id,
        "interval_seconds": interval,
        "enabled": config.TRAJECTORY_CLEANUP_ENABLED,
        "retention_days": config.TRAJECTORY_RETENTION_DAYS,
    }


def read_schedule(actor, tenant_id=None):
    tenant = tenant_id or actor.tenant_id
    authorize(TrajectoryCatalog(), actor, tenant)
    try:
        value = CleanupScheduleRepository().read(tenant)
    except (ValueError, TypeError) as error:
        raise QueryError("trajectory_configuration_invalid", 503) from error
    return _policy(
        tenant, config.TRAJECTORY_CLEANUP_INTERVAL_SECONDS if value is None else value
    )


def save_schedule(actor, interval_seconds, tenant_id=None):
    tenant = tenant_id or actor.tenant_id
    authorize(TrajectoryCatalog(), actor, tenant)
    value = CleanupScheduleRequest(interval_seconds=interval_seconds).interval_seconds
    CleanupScheduleRepository().save(tenant, value, actor.user_id)
    logger.info(
        "trajectory.cleanup_schedule_saved actor_id=%s tenant_id=%s interval_seconds=%s",
        actor.user_id,
        tenant,
        value,
    )
    return _policy(tenant, value)
