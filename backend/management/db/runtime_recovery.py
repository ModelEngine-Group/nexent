# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Management compatibility helpers for exact recovery and evaluation claims."""

from sqlalchemy import func, update

from contracts.evaluation import EvalRunStatus
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.sandbox_recovery import _positive_id, fail_exact_owned_work as _fail_exact_owned_work
from management.db.models import AgentEvaluation


def claim_owned_evaluation_run(evaluation_id, tenant_id, user_id):
    """Return the existing audit timestamp for exact unstarted-claim compensation."""
    evaluation_id = _positive_id(evaluation_id)
    if evaluation_id is None:
        raise ValueError('Invalid evaluation identity')
    with get_db_session() as session:
        result = session.execute(
            update(AgentEvaluation).where(
                AgentEvaluation.agent_evaluation_id == evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.delete_flag == 'N',
                AgentEvaluation.status == EvalRunStatus.PENDING,
            ).values(status=EvalRunStatus.RUNNING, updated_by=user_id, update_time=func.current_timestamp())
            .returning(AgentEvaluation.update_time)
        ).first()
        return result[0] if result is not None else None


def restore_unstarted_evaluation_run(evaluation_id, tenant_id, user_id, claim_time):
    """Only a caller that never bound its worker may use this compensation."""
    evaluation_id = _positive_id(evaluation_id)
    if evaluation_id is None or claim_time is None:
        raise ValueError('Exact evaluation claim observation is required')
    with get_db_session() as session:
        result = session.execute(update(AgentEvaluation).where(
            AgentEvaluation.agent_evaluation_id == evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.delete_flag == 'N',
            AgentEvaluation.status == EvalRunStatus.RUNNING,
            AgentEvaluation.updated_by == user_id,
            AgentEvaluation.update_time == claim_time,
        ).values(status=EvalRunStatus.PENDING, updated_by=user_id, update_time=func.current_timestamp()))
        return result.rowcount == 1


def fail_exact_owned_work(**associations):
    return _fail_exact_owned_work(session_factory=get_db_session, **associations)
