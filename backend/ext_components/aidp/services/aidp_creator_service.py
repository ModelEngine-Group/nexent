"""Resolve AIDP permission owners to Nexent account names without remote identity lookup."""

import logging
from collections.abc import Iterable

from database.user_tenant_db import get_user_email_map


logger = logging.getLogger(__name__)


def get_nexent_creator_names(user_ids: Iterable[str], tenant_id: str) -> dict[str, str]:
    """Use the same account name as user management, scoped to the current tenant."""
    ids = sorted({str(user_id) for user_id in user_ids if user_id})
    if not ids:
        return {}
    try:
        return get_user_email_map(ids, tenant_id=tenant_id)
    except Exception:
        # Missing identity metadata must not make the knowledge base inaccessible.
        logger.exception("Failed to resolve Nexent AIDP creator names")
        return {}
