# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Update trajectory projections in Management-owned transactions."""

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from infrastructure.rdb.account_record import UserTenant
from infrastructure.rdb.conversation_record import ConversationRecord
from infrastructure.rdb.trajectory_record import TrajectoryExecution as Execution
from infrastructure.rdb.trajectory_repository import dirty, placeholder_uuid


def seed_conversation(session, conversation_id, owner, agent_id):
    inserted = session.execute(
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
    if inserted.rowcount == 0:
        return
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
