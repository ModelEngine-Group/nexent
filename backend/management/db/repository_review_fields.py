# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read-only compatibility projections; no review columns live in repository tables."""

from management.db.resource_review_model import ResourceReview
from sqlalchemy import func, select
from sqlalchemy.orm import column_property, declared_attr


class RepositoryReviewFields:
    @declared_attr
    def published_at(cls):
        kind, key = {
            "ag_agent_repository_t": ("agent", "agent_repository_id"),
            "ag_skill_repository_t": ("skill", "skill_repository_id"),
            "mcp_market_record_t": ("mcp", "market_id"),
        }[cls.__tablename__]
        return column_property(
            select(func.max(ResourceReview.reviewed_at))
            .where(
                ResourceReview.resource_type == kind,
                ResourceReview.repository_id == getattr(cls, key),
                ResourceReview.tenant_id
                == getattr(
                    cls, "tenant_id" if kind == "mcp" else "publisher_tenant_id"
                ),
                ResourceReview.review_status == "approved",
                ResourceReview.delete_flag == "N",
            )
            .correlate_except(ResourceReview)
            .scalar_subquery()
        )

    @declared_attr
    def submitted_user_id(cls):
        kind, key = {
            "ag_agent_repository_t": ("agent", "agent_repository_id"),
            "ag_skill_repository_t": ("skill", "skill_repository_id"),
            "mcp_market_record_t": ("mcp", "market_id"),
        }[cls.__tablename__]
        return column_property(
            select(ResourceReview.submitted_user_id)
            .where(
                ResourceReview.resource_type == kind,
                ResourceReview.repository_id == getattr(cls, key),
                ResourceReview.tenant_id
                == getattr(
                    cls, "tenant_id" if kind == "mcp" else "publisher_tenant_id"
                ),
                ResourceReview.delete_flag == "N",
            )
            .order_by(ResourceReview.review_id.desc())
            .limit(1)
            .correlate_except(ResourceReview)
            .scalar_subquery()
        )
