# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Transactional projections; conversation rows serialize execution registration."""

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import md5
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

# isort: split
from management.db.client import get_db_session
from management.db.conversation.models import ConversationRecord
from management.db.identity.models import UserTenant
from management.db.trajectory.models import TrajectoryExecution as Execution
from management.db.trajectory.models import TrajectoryStatistics as Statistics


def scope_uuid(kind, identity):
    return str(uuid5(NAMESPACE_URL, f"nexent:trajectory:{kind}:{identity}"))


def placeholder_uuid(conversation_id):
    from uuid import UUID

    return str(
        UUID(md5(f"trajectory:placeholder:{conversation_id}".encode()).hexdigest())
    )


def dirty(session, tenant_id):
    """Change counters survive restarts and are never replaced by computed values."""
    tenants = [tenant_id] if isinstance(tenant_id, str) else sorted(set(tenant_id))
    # Lock every tenant scope before the shared global scope to avoid lock inversion.
    for kind, identity in [("tenant", value) for value in tenants] + [
        ("global", "global")
    ]:
        stmt = insert(Statistics).values(
            statistics_id=scope_uuid(kind, identity),
            scope_type=kind,
            scope_id=identity,
            source_revision=1,
            computed_revision=0,
            complete=False,
            definition_version=1,
            created_by="trajectory",
            updated_by="trajectory",
            delete_flag="N",
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Statistics.statistics_id],
                set_={
                    "source_revision": Statistics.source_revision + 1,
                    "updated_by": "trajectory",
                    "update_time": func.now(),
                },
            )
        )


def seed_conversation(session, conversation_id, owner, agent_id):
    session.execute(
        insert(Execution)
        .values(
            trajectory_id=placeholder_uuid(conversation_id),
            conversation_id=conversation_id,
            turn_no=0,
            agent_id=agent_id,
            models=[],
            status="not_captured",
            created_by=owner,
            updated_by=owner,
            delete_flag="N",
        )
        .on_conflict_do_nothing(index_elements=[Execution.trajectory_id])
    )
    tenants = (
        session.execute(
            select(UserTenant.tenant_id).where(
                UserTenant.user_id == owner,
                UserTenant.delete_flag == "N",
            )
        )
        .scalars()
        .all()
    )
    if tenants:
        dirty(session, sorted(set(tenants)))


def delete_summaries(session, conversation_ids, user_id):
    """Participate in the caller's conversation deletion transaction."""
    session.execute(
        update(Execution)
        .where(
            Execution.conversation_id.in_(conversation_ids),
            Execution.delete_flag == "N",
        )
        .values(delete_flag="Y", updated_by=user_id, update_time=func.now())
    )
    tenants = (
        session.execute(
            select(UserTenant.tenant_id).where(
                UserTenant.user_id.in_(
                    select(ConversationRecord.created_by).where(
                        ConversationRecord.conversation_id.in_(conversation_ids)
                    )
                ),
                UserTenant.delete_flag == "N",
            )
        )
        .scalars()
        .all()
    )
    if tenants:
        dirty(session, sorted(set(tenants)))


def detach_owner(session, user_id, old_tenant, new_tenant):
    """Revoke fixed archive identities atomically with a tenant membership change."""
    session.execute(
        update(Execution)
        .where(Execution.created_by == user_id, Execution.delete_flag == "N")
        .values(delete_flag="Y", updated_by="trajectory", update_time=func.now())
    )
    # Reuse the stable placeholder, including when a previous run replaced it.
    session.execute(
        text("""INSERT INTO nexent.trajectory_execution_t
          (trajectory_id,conversation_id,turn_no,agent_id,models,status,created_by,updated_by,delete_flag)
          SELECT md5('trajectory:placeholder:' || c.conversation_id)::uuid,
            c.conversation_id,0,c.agent_id,'{}','not_captured',c.created_by,'trajectory','N'
          FROM nexent.conversation_record_t c WHERE c.created_by=:owner AND c.delete_flag='N'
          ON CONFLICT (trajectory_id) DO UPDATE
          SET delete_flag='N',updated_by='trajectory',update_time=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')"""),
        {"owner": user_id},
    )
    dirty(session, sorted({old_tenant, new_tenant}))


class ExecutionRepository:
    @staticmethod
    def _owner(session, identity):
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SET LOCAL statement_timeout = '30000ms'"))
        row = session.execute(
            select(ConversationRecord)
            .where(
                ConversationRecord.conversation_id == int(identity.conversation_id),
                ConversationRecord.created_by == identity.owner_user_id,
                ConversationRecord.delete_flag == "N",
            )
            .with_for_update()
        ).scalar_one_or_none()
        member = session.execute(
            select(UserTenant.user_id)
            .where(
                UserTenant.user_id == identity.owner_user_id,
                UserTenant.tenant_id == identity.tenant_id,
                UserTenant.delete_flag == "N",
            )
            .with_for_update(read=True)
        ).first()
        if row is None or member is None:
            raise PermissionError("Trajectory owner is no longer authorized")
        return row

    @contextmanager
    def initialize(self, identity):
        with get_db_session() as session:
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            self._owner(session, identity)
            yield

    def begin(
        self,
        identity,
        trajectory_id,
        *,
        agent_version_no=None,
        capturing=True,
        prior_turn=0,
    ):
        with get_db_session() as session:
            self._owner(session, identity)
            previous = session.get(Execution, trajectory_id)
            if previous is not None:
                if (previous.conversation_id, previous.created_by) != (
                    int(identity.conversation_id),
                    identity.owner_user_id,
                ) or previous.delete_flag != "N":
                    raise PermissionError("Execution identity differs")
                return previous.turn_no
            turn = (
                session.execute(
                    select(func.max(Execution.turn_no)).where(
                        Execution.conversation_id == int(identity.conversation_id),
                    )
                ).scalar()
                or 0
            ) + 1
            turn = max(turn, prior_turn + 1)
            session.execute(
                update(Execution)
                .where(
                    Execution.conversation_id == int(identity.conversation_id),
                    Execution.turn_no == 0,
                )
                .values(
                    delete_flag="Y",
                    updated_by=identity.owner_user_id,
                    update_time=func.now(),
                )
            )
            session.add(
                Execution(
                    trajectory_id=trajectory_id,
                    conversation_id=int(identity.conversation_id),
                    turn_no=turn,
                    agent_id=int(identity.root_agent_id)
                    if identity.root_agent_id
                    else None,
                    agent_version_no=agent_version_no
                    if type(agent_version_no) is int
                    and 0 <= agent_version_no <= 2147483647
                    else None,
                    models=[],
                    status="unarchived" if capturing else "not_captured",
                    started_at=datetime.now(UTC),
                    created_by=identity.owner_user_id,
                    updated_by=identity.owner_user_id,
                    delete_flag="N",
                )
            )
            dirty(session, identity.tenant_id)
            return turn

    def sync(self, identity, values):
        """Idempotent compensation cannot revive deleted or logically expired rows."""
        with get_db_session() as session:
            self._owner(session, identity)
            current = session.get(Execution, values["trajectory_id"])
            if current is not None and (
                current.delete_flag != "N" or current.status == "expired"
            ):
                return
            values = {
                **values,
                "updated_by": identity.owner_user_id,
                "update_time": func.now(),
            }
            if current is not None:
                if (
                    current.conversation_id != int(identity.conversation_id)
                    or current.created_by != identity.owner_user_id
                ):
                    raise PermissionError("Execution identity differs")
                # The ingress allocation is authoritative across capture outages.
                values["turn_no"] = current.turn_no
                if all(
                    getattr(current, k) == v
                    for k, v in values.items()
                    if k not in {"update_time", "updated_by"}
                ):
                    return
                session.execute(
                    update(Execution)
                    .where(Execution.trajectory_id == current.trajectory_id)
                    .values(**values)
                )
            else:
                session.add(
                    Execution(
                        **values, created_by=identity.owner_user_id, delete_flag="N"
                    )
                )
            session.execute(
                update(Execution)
                .where(
                    Execution.conversation_id == int(identity.conversation_id),
                    Execution.turn_no == 0,
                )
                .values(
                    delete_flag="Y",
                    updated_by=identity.owner_user_id,
                    update_time=func.now(),
                )
            )
            dirty(session, identity.tenant_id)

    def expire(self, identity, ids):
        if not ids:
            return
        with get_db_session() as session:
            result = session.execute(
                update(Execution)
                .where(
                    Execution.trajectory_id.in_(ids),
                    Execution.created_by == identity.owner_user_id,
                    Execution.conversation_id == int(identity.conversation_id),
                    Execution.delete_flag == "N",
                    Execution.status != "expired",
                )
                .values(
                    status="expired", updated_by="trajectory", update_time=func.now()
                )
            )
            if result.rowcount:
                dirty(session, identity.tenant_id)

    def placeholders(self, limit=1000):
        """Bounded catch-up for conversations created while this worker was down."""
        with get_db_session() as session:
            missing = (
                ~select(Execution.trajectory_id)
                .where(
                    Execution.conversation_id == ConversationRecord.conversation_id,
                )
                .exists()
            )
            rows = (
                session.execute(
                    select(ConversationRecord)
                    .where(
                        ConversationRecord.delete_flag == "N",
                        missing,
                    )
                    .order_by(ConversationRecord.conversation_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            owners = {row.created_by for row in rows}
            tenants = (
                session.execute(
                    select(UserTenant.user_id, UserTenant.tenant_id).where(
                        UserTenant.user_id.in_(owners),
                        UserTenant.delete_flag == "N",
                    )
                ).all()
                if owners
                else []
            )
            for row in rows:
                session.execute(
                    insert(Execution)
                    .values(
                        trajectory_id=placeholder_uuid(row.conversation_id),
                        conversation_id=row.conversation_id,
                        turn_no=0,
                        agent_id=row.agent_id,
                        models=[],
                        status="not_captured",
                        created_by=row.created_by,
                        updated_by="trajectory",
                        delete_flag="N",
                    )
                    .on_conflict_do_nothing(index_elements=[Execution.trajectory_id])
                )
            if tenants:
                dirty(session, sorted({t for _, t in tenants}))
            return len(rows)

    def compact(self, limit=1000):
        """Reclaim old tombstones while retaining each active conversation's latest state."""
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            ids = (
                session.execute(
                    text("""SELECT e.trajectory_id FROM nexent.trajectory_execution_t e
              WHERE e.update_time < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - INTERVAL '7 days'
              AND (e.delete_flag='Y' OR e.status='expired' AND EXISTS (
                SELECT 1 FROM nexent.trajectory_execution_t newer
                WHERE newer.conversation_id=e.conversation_id AND newer.turn_no>e.turn_no
                  AND newer.delete_flag='N'))
              ORDER BY e.update_time,e.trajectory_id LIMIT :limit FOR UPDATE SKIP LOCKED"""),
                    {"limit": limit},
                )
                .scalars()
                .all()
            )
            if ids:
                session.execute(
                    delete(Execution).where(Execution.trajectory_id.in_(ids))
                )
            return len(ids)
