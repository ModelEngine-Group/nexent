# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Business-database adapter for trusted trajectory capture and deletion checks."""

from contextlib import contextmanager

from sqlalchemy import select, text

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from contracts.errors.trajectory import QueryError
from contracts.roles import has_any_role, roles_from_record
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.orm import as_dict


@contextmanager
def _session():
    with get_db_session() as session:
        session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
        yield session


class CaptureCatalog:
    def authorize(self, identity):
        """Check the active membership, effective tenant, and live conversation owner."""
        with _session() as session:
            memberships = select(UserTenant).where(
                UserTenant.user_id == identity.owner_user_id, UserTenant.delete_flag == "N",
            )
            member = session.scalars(memberships.where(UserTenant.tenant_id == identity.tenant_id)).first()
            if member is None:
                raise PermissionError("Trajectory capture owner is not an active tenant member")
            current = session.scalars(memberships).first()
            if current is not None:
                effective = current.tenant_id or (
                    ASSET_OWNER_TENANT_ID
                    if has_any_role(roles_from_record(as_dict(current)), {ASSET_OWNER_ROLE})
                    else DEFAULT_TENANT_ID
                )
                if effective == identity.tenant_id and not self._conversation_deleted(
                    session, identity.conversation_id, identity.owner_user_id,
                ):
                    return
            raise PermissionError("Trajectory capture conversation ownership differs")

    @staticmethod
    def _query(session, tenants):
        return (
            session.query(
                ConversationRecord,
                UserTenant.tenant_id,
                UserAccount.user_email,
            )
            .join(
                UserTenant,
                UserTenant.user_id == ConversationRecord.created_by,
            )
            .join(UserAccount, UserAccount.user_id == UserTenant.user_id)
            .filter(
                UserTenant.tenant_id.in_(tenants),
                UserTenant.delete_flag == "N",
                UserAccount.delete_flag == "N",
                ConversationRecord.delete_flag == "N",
            )
        )

    @staticmethod
    def _conversation_deleted(session, conversation_id, owner):
        return (
            session.query(ConversationRecord.conversation_id)
            .filter(
                ConversationRecord.conversation_id == int(conversation_id),
                ConversationRecord.created_by == owner,
                ConversationRecord.delete_flag == "N",
            )
            .first()
            is None
        )

    def conversation_deleted(self, conversation_id, owner):
        with _session() as session:
            return self._conversation_deleted(session, conversation_id, owner)

    def source_messages(
        self, tenant_id, user_id, conversation_id, *, upper=None, limit=10_000
    ):
        """Retain soft-deleted user identities when checking historical capture gaps."""
        if not 1 <= limit <= 10_000:
            raise ValueError("Trajectory source limit is invalid")
        with _session() as session:
            query = (
                self._query(session, [tenant_id])
                .join(
                    ConversationMessage,
                    ConversationMessage.conversation_id
                    == ConversationRecord.conversation_id,
                )
                .with_entities(ConversationMessage.message_id)
                .filter(
                    ConversationRecord.conversation_id == int(conversation_id),
                    ConversationRecord.created_by == user_id,
                    ConversationMessage.message_role == "user",
                )
            )
            if upper is not None:
                query = query.filter(ConversationMessage.message_id <= int(upper))
            rows = query.order_by(ConversationMessage.message_id).limit(limit + 1).all()
        if len(rows) > limit:
            raise QueryError("source_coverage_budget_exceeded", 503, retry_after=2)
        return [str(row[0]) for row in rows]
