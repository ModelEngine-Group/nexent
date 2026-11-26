# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared Agent-monitoring eligibility for directories and published statistics."""

from sqlalchemy import or_, select

from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo


WORKBENCH_SYSTEM_KEY = "workbench_main"


def monitored_agent_predicate():
    """Keep business Agents, including rows without a system identity."""
    return or_(AgentInfo.system_key.is_(None), AgentInfo.system_key != WORKBENCH_SYSTEM_KEY)


def excluded_monitoring_agent_ids() -> set[int]:
    """Resolve system IDs across owners, versions and soft-deleted metadata.

    System executions carry the requesting tenant, not the asset-owner tenant.
    Parent/root IDs deliberately do not participate in monitoring eligibility.
    """
    statement = select(AgentInfo.agent_id).where(AgentInfo.system_key == WORKBENCH_SYSTEM_KEY).distinct()
    with get_db_session() as session:
        return set(session.scalars(statement))
