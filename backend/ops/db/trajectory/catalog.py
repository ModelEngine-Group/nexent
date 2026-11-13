# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded trajectory catalog queries using existing ownership and message tables."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import String, cast, func, or_, text

# isort: split
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.trajectory import QueryError
from management.db.client import get_db_session
from management.db.conversation.classification import is_workbench_history
from management.db.conversation.models import ConversationMessage, ConversationRecord
from management.db.models import AgentInfo, TenantConfig, UserAccount, UserTenant


@contextmanager
def _session():
    with get_db_session() as session:
        session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
        yield session


class TrajectoryCatalog:
    def tenants(self, actor):
        if actor.role == "ADMIN":
            return [actor.tenant_id]
        with _session() as session:
            rows = (
                session.query(UserTenant.tenant_id)
                .filter(UserTenant.delete_flag == "N")
                .distinct()
                .order_by(UserTenant.tenant_id)
                .limit(1001)
                .all()
            )
        if len(rows) > 1000:
            raise QueryError("tenant_scope_budget_exceeded", 503, retry_after=2)
        return [row[0] for row in rows]

    def actor_active(self, actor):
        with _session() as session:
            return (
                session.query(UserTenant.user_id)
                .join(UserAccount, UserAccount.user_id == UserTenant.user_id)
                .filter(
                    UserTenant.user_id == actor.user_id,
                    UserTenant.tenant_id == actor.tenant_id,
                    UserTenant.delete_flag == "N",
                    UserAccount.delete_flag == "N",
                    UserAccount.user_role == actor.role,
                )
                .first()
                is not None
            )

    @staticmethod
    def _query(session, tenants):
        return (
            session.query(
                ConversationRecord,
                UserTenant.tenant_id,
                UserAccount.user_email,
                is_workbench_history(),
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
    def _row(row):
        conversation, tenant_id, email, workbench = row
        return {
            "tenant_id": tenant_id,
            "user_id": conversation.created_by,
            "user_name": email or conversation.created_by,
            "conversation_id": str(conversation.conversation_id),
            "conversation_title": conversation.conversation_title,
            "agent_id": str(conversation.agent_id) if conversation.agent_id else None,
            "category": "workbench" if workbench else "agent_chat",
        }

    def candidates(
        self, tenants, *, target_user_id=None, conversation_id=None, limit=10_000
    ):
        with _session() as session:
            query = self._query(session, tenants)
            if target_user_id:
                query = query.filter(ConversationRecord.created_by == target_user_id)
            if conversation_id:
                query = query.filter(
                    ConversationRecord.conversation_id == int(conversation_id)
                )
            rows = (
                query.order_by(ConversationRecord.conversation_id)
                .limit(limit + 1)
                .all()
            )
            if len(rows) > limit:
                raise QueryError("candidate_budget_exceeded", 503, retry_after=2)
            return [self._row(row) for row in rows]

    def resolve(self, tenants, conversation_id, *, target_user_id=None):
        rows = self.candidates(
            tenants,
            target_user_id=target_user_id,
            conversation_id=conversation_id,
            limit=2,
        )
        if len(rows) != 1:
            raise QueryError("trajectory_not_found", 404)
        return rows[0]

    def names(self, tenants):
        with _session() as session:
            names = (
                session.query(TenantConfig.tenant_id, TenantConfig.config_value)
                .filter(
                    TenantConfig.tenant_id.in_(tenants),
                    TenantConfig.config_key == "TENANT_NAME",
                    TenantConfig.delete_flag == "N",
                )
                .limit(1001)
                .all()
            )
        return dict(names)

    def agent_names(self, tenants, ids):
        if not ids:
            return {}
        with _session() as session:
            rows = (
                session.query(
                    AgentInfo.tenant_id,
                    AgentInfo.agent_id,
                    func.coalesce(AgentInfo.display_name, AgentInfo.name),
                )
                .filter(
                    AgentInfo.tenant_id.in_([*tenants, ASSET_OWNER_TENANT_ID]),
                    AgentInfo.agent_id.in_([int(i) for i in ids]),
                    AgentInfo.delete_flag == "N",
                    AgentInfo.version_no == 0,
                )
                .limit(10_001)
                .all()
            )
            if len(rows) > 10_000:
                raise QueryError("agent_budget_exceeded", 503, retry_after=2)
            available = {(tenant, str(agent)): name for tenant, agent, name in rows}
            return {
                (tenant, str(agent)): available.get(
                    (tenant, str(agent)),
                    available.get((ASSET_OWNER_TENANT_ID, str(agent)), str(agent)),
                )
                for tenant in tenants
                for agent in ids
            }

    def directory_page(
        self, tenant_id, user_id, category, group_key, after, limit, search
    ):
        from management.db.identity.conversation_agent_history_db import (
            _agent_group_name,
            _escape_like,
        )

        with _session() as session:
            base = self._query(session, [tenant_id]).filter(
                ConversationRecord.created_by == user_id
            )
            base = base.filter(
                is_workbench_history()
                if category == "workbench"
                else ~is_workbench_history()
            )
            if group_key is not None:
                base = base.filter(
                    ConversationRecord.agent_id.is_(None)
                    if group_key == "other"
                    else ConversationRecord.agent_id == int(group_key[6:])
                )
                base = base.filter(ConversationRecord.conversation_id > after)
                if search:
                    pattern = "%" + _escape_like(search) + "%"
                    base = base.filter(
                        or_(
                            ConversationRecord.conversation_title.ilike(
                                pattern, escape="\\"
                            ),
                            cast(ConversationRecord.conversation_id, String).ilike(
                                pattern, escape="\\"
                            ),
                        )
                    )
                rows = (
                    base.order_by(ConversationRecord.conversation_id)
                    .limit(limit + 1)
                    .all()
                )
                return [self._row(row) for row in rows]
            group_id = func.coalesce(ConversationRecord.agent_id, 0)
            query = base.with_entities(
                group_id, func.max(ConversationRecord.conversation_id)
            ).filter(group_id > after)
            if search:
                pattern = "%" + _escape_like(search) + "%"
                query = query.filter(
                    or_(
                        _agent_group_name(ConversationRecord.agent_id, tenant_id).ilike(
                            pattern, escape="\\"
                        ),
                        cast(group_id, String).ilike(pattern, escape="\\"),
                    )
                )
            ids = [
                row[1]
                for row in query.group_by(group_id)
                .order_by(group_id)
                .limit(limit + 1)
                .all()
            ]
            rows = (
                base.filter(ConversationRecord.conversation_id.in_(ids)).all()
                if ids
                else []
            )
            return sorted(
                (self._row(row) for row in rows),
                key=lambda row: int(row["agent_id"]) if row["agent_id"] else 0,
            )

    def user_active(self, tenant_id, user_id):
        with _session() as session:
            return (
                session.query(UserTenant.user_id)
                .join(UserAccount, UserAccount.user_id == UserTenant.user_id)
                .filter(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.user_id == user_id,
                    UserTenant.delete_flag == "N",
                    UserAccount.delete_flag == "N",
                )
                .first()
                is not None
            )

    def conversation_deleted(self, conversation_id, owner):
        with _session() as session:
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

    def cleanup_candidates(self, tenant_id, after, *, limit):
        with _session() as session:
            rows = (
                self._query(session, [tenant_id])
                .filter(
                    ConversationRecord.conversation_id >= after,
                )
                .order_by(ConversationRecord.conversation_id)
                .limit(limit)
                .all()
            )
            return [self._row(row) for row in rows]

    def user_page(self, tenants, search, after, limit):
        from management.db.identity.conversation_agent_history_db import _escape_like
        from sqlalchemy import and_

        with _session() as session:
            query = (
                session.query(
                    UserTenant.tenant_id, UserTenant.user_id, UserAccount.user_email
                )
                .join(
                    UserAccount,
                    UserAccount.user_id == UserTenant.user_id,
                )
                .filter(
                    UserTenant.tenant_id.in_(tenants),
                    UserTenant.delete_flag == "N",
                    UserAccount.delete_flag == "N",
                )
            )
            if search:
                pattern = "%" + _escape_like(search) + "%"
                query = query.filter(
                    or_(
                        UserAccount.user_email.ilike(pattern, escape="\\"),
                        UserTenant.user_id.ilike(pattern, escape="\\"),
                    )
                )
            if after:
                query = query.filter(
                    or_(
                        UserTenant.tenant_id > after[0],
                        and_(
                            UserTenant.tenant_id == after[0],
                            UserTenant.user_id > after[1],
                        ),
                    )
                )
            rows = (
                query.order_by(UserTenant.tenant_id, UserTenant.user_id)
                .limit(limit + 1)
                .all()
            )
        return [
            {"id": user, "name": email or user, "tenant_id": tenant}
            for tenant, user, email in rows
        ]

    def message_upper(self, conversation_id):
        with _session() as session:
            return (
                session.query(func.max(ConversationMessage.message_id))
                .filter(
                    ConversationMessage.conversation_id == int(conversation_id),
                    ConversationMessage.delete_flag == "N",
                )
                .scalar()
                or 0
            )

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

    def messages(self, conversation_id, upper, after, limit):
        # Only previews are transferred from PG; large bodies use bounded substrings.
        with _session() as session:
            rows = (
                session.query(
                    ConversationMessage.message_id,
                    ConversationMessage.message_role,
                    func.substr(ConversationMessage.message_content, 1, 4096),
                    func.length(ConversationMessage.message_content),
                    func.octet_length(ConversationMessage.message_content),
                    func.md5(ConversationMessage.message_content),
                    ConversationMessage.status,
                )
                .filter(
                    ConversationMessage.conversation_id == int(conversation_id),
                    ConversationMessage.delete_flag == "N",
                    ConversationMessage.message_id > after,
                    ConversationMessage.message_id <= upper,
                )
                .order_by(ConversationMessage.message_id)
                .limit(limit + 1)
                .all()
            )
        return [
            {
                "message_id": str(r[0]),
                "role": r[1],
                "preview": (r[2] or "").encode()[:4096].decode("utf8", errors="ignore"),
                "char_count": r[3] or 0,
                "byte_count": r[4] or 0,
                "hash": r[5],
                "status": r[6],
            }
            for r in rows
        ]

    def message_content(self, conversation_id, message_id, offset, count):
        """Return a bounded byte slice; count=0 retrieves only current version metadata."""
        with _session() as session:
            row = (
                session.query(
                    func.substr(
                        func.convert_to(ConversationMessage.message_content, "UTF8"),
                        offset + 1,
                        count,
                    ),
                    func.md5(ConversationMessage.message_content),
                    func.length(ConversationMessage.message_content),
                    func.octet_length(ConversationMessage.message_content),
                )
                .filter(
                    ConversationMessage.conversation_id == int(conversation_id),
                    ConversationMessage.message_id == int(message_id),
                    ConversationMessage.delete_flag == "N",
                )
                .first()
            )
        return row
