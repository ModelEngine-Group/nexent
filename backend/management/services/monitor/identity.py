# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve display identity without changing authorization or accounting IDs."""

import logging

from management.db.identity.user_tenant import get_user_tenant_in_tenant

logger = logging.getLogger(__name__)


def resolve_monitoring_user_email(user_id: str, tenant_id: str) -> str | None:
    """Use the tenant's stored email; enrichment must not prevent a run."""
    if not user_id or not tenant_id:
        return None
    try:
        user = get_user_tenant_in_tenant(user_id, tenant_id)
        email = user.get("user_email") if user else None
        if isinstance(email, str):
            return email.strip() or None
        return None
    except Exception:  # noqa: BLE001 - Optional enrichment must not interrupt execution.
        logger.debug("Unable to resolve monitoring user email")
        return None
