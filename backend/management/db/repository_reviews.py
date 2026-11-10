# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorized review-table queries and legacy repository mappings."""

from management.db.agent.models import AgentRepository
from management.db.mcp.models import McpMarketRecord
from management.db.resource_review_model import ResourceReview
from management.db.skill.models import SkillRepository
from sqlalchemy import and_, func, or_, select

REVIEW_MODELS = {
    "agent": (
        AgentRepository,
        "agent_repository_id",
        "publisher_tenant_id",
        "status",
        "agent_id",
    ),
    "skill": (
        SkillRepository,
        "skill_repository_id",
        "publisher_tenant_id",
        "status",
        "skill_id",
    ),
    "mcp": (
        McpMarketRecord,
        "market_id",
        "tenant_id",
        "review_status",
        "source_mcp_id",
    ),
}


def scope_conditions(resource_type, user_id, tenant_id, role):
    r = ResourceReview
    conditions = [r.delete_flag == "N", r.resource_type == resource_type]
    global_mcp = resource_type == "mcp" and role in {"SU", "SUPER_ADMIN"}
    if not global_mcp:
        conditions.append(r.tenant_id == tenant_id)
    if role != "ADMIN" and not global_mcp:
        conditions.append(r.submitted_user_id == user_id)
    return conditions


def authorized_scope(user_id, tenant_id, role):
    return or_(
        *(
            and_(*scope_conditions(kind, user_id, tenant_id, role))
            for kind in REVIEW_MODELS
        )
    )


def list_reviews(session, user_id, tenant_id, role, query):
    r = ResourceReview
    filters = [authorized_scope(user_id, tenant_id, role)]
    if query.resource_type != "all":
        filters.append(r.resource_type == query.resource_type)
    if query.status != "all":
        filters.append(r.review_status == query.status)
    if query.search:
        filters.append(
            r.resource_snapshot["payload"]["display_name"].astext.icontains(
                query.search, autoescape=True
            )
            | r.resource_snapshot["payload"]["name"].astext.icontains(
                query.search, autoescape=True
            )
            | r.resource_snapshot["payload"]["mcp_name"].astext.icontains(
                query.search, autoescape=True
            )
        )
    total = session.scalar(select(func.count()).select_from(r).where(*filters))
    rows = session.scalars(
        select(r)
        .where(*filters)
        .order_by(r.submitted_at.desc(), r.review_id.desc())
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    ).all()
    return rows, int(total or 0)


def get_review(session, review_id, user_id, tenant_id, role, *, for_update=False):
    statement = select(ResourceReview).where(
        ResourceReview.review_id == review_id,
        authorized_scope(user_id, tenant_id, role),
    )
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return session.scalar(statement)
