# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read display-only CAS identities for explicitly linked platform users."""

from typing import Dict, Iterable, Optional

from sqlalchemy import select

from management.db.client import get_db_session
from management.db.models import AgentInfo, AgentRepository, UserOAuthAccount, UserTenant


def get_cas_identities(user_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Return active CAS names and canonical emails in one bounded query."""
    ids = sorted({value for value in user_ids if isinstance(value, str) and value})
    if not ids:
        return {}
    statement = (
        select(UserOAuthAccount.user_id, UserOAuthAccount.provider_username, UserTenant.user_email)
        .join(UserTenant, UserTenant.user_id == UserOAuthAccount.user_id)
        .where(
            UserOAuthAccount.user_id.in_(ids),
            UserOAuthAccount.provider == "cas",
            UserOAuthAccount.delete_flag == "N",
            UserTenant.delete_flag == "N",
        )
        .order_by(UserOAuthAccount.oauth_account_id.asc())
    )
    with get_db_session() as session:
        rows = session.execute(statement).all()
        identities = {}
        for user_id, username, email in rows:
            name = (username or "").strip()
            if name and user_id not in identities:
                identities[user_id] = {"cas_username": name, "email": (email or "").strip()}
        return identities


def get_repository_agent_identity_ids(repository_ids: Iterable[int]) -> Dict[int, Dict[str, Optional[str]]]:
    """Read creators only through a listing's explicit tenant/version association."""
    ids = sorted({value for value in repository_ids if isinstance(value, int)})
    if not ids:
        return {}
    statement = (
        select(AgentRepository.agent_repository_id, AgentInfo.created_by, AgentRepository.publisher_user_id)
        .outerjoin(
            AgentInfo,
            (AgentInfo.agent_id == AgentRepository.agent_id)
            & (AgentInfo.tenant_id == AgentRepository.publisher_tenant_id)
            & (AgentInfo.version_no == AgentRepository.version_no)
            & (AgentInfo.delete_flag == "N"),
        )
        .where(AgentRepository.agent_repository_id.in_(ids), AgentRepository.delete_flag == "N")
    )
    with get_db_session() as session:
        return {
            repository_id: {"author_id": creator, "submitter_id": publisher}
            for repository_id, creator, publisher in session.execute(statement).all()
        }
