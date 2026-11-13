# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conditional recovery of exact business identities, without schema changes."""

from sqlalchemy import exists, func, select, update

from contracts.evaluation import EvalRunStatus
from management.db.client import get_db_session
from management.db.models import (
    AgentAutomationRun,
    AgentAutomationTask,
    AgentEvaluation,
    AgentEvaluationCase,
    ConversationMessage,
)


def _positive_id(value):
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < len(value) <= 20:
        parsed = int(value)
        return parsed if 0 < parsed <= 2**63 - 1 else None
    return None


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


def fail_exact_owned_work(*, tenant_id, user_id, conversation_id, assistant_message_id=None,
                          evaluation_id=None, evaluation_case_id=None, automation_run_id=None,
                          automation_task_id=None, automation_lock_owner=None, evaluation_batch=False):
    """The caller must first prove the old Runtime and execution container ended.

    Missing/corrupt associations never broaden a query. All status transitions
    remain conditional, so user cancellation and already-completed work survive.
    """
    message_id, evaluation_id, case_id, automation_id, task_id = map(_positive_id, (
        assistant_message_id, evaluation_id, evaluation_case_id, automation_run_id, automation_task_id,
    ))
    conversation = _positive_id(conversation_id)
    if type(evaluation_batch) is not bool:
        raise TypeError('Evaluation recovery scope must be explicit')
    if evaluation_batch and evaluation_case_id is not None:
        raise ValueError('Batch recovery cannot carry a child-case identity')
    if any(not isinstance(value, str) or not value for value in (tenant_id, user_id)):
        raise ValueError('Trusted recovery tenant and user identities are required')
    recover_evaluation = evaluation_id is not None and (evaluation_batch or case_id is not None)
    result = {'conversation_messages': 0, 'agent_evaluations': 0, 'evaluation_cases': 0,
              'automation_runs': 0, 'automation_locks': 0}
    if not any((message_id and conversation, recover_evaluation, automation_id and conversation)):
        return result
    with get_db_session() as session:
        if message_id and conversation:
            updated = session.execute(update(ConversationMessage).where(
                ConversationMessage.message_id == message_id,
                ConversationMessage.conversation_id == conversation,
                ConversationMessage.created_by == user_id,
                ConversationMessage.message_role == 'assistant',
                ConversationMessage.status == 'streaming',
                ConversationMessage.delete_flag == 'N',
            ).values(status='failed', updated_by=user_id, update_time=func.current_timestamp()))
            result['conversation_messages'] = max(0, updated.rowcount or 0)
        if recover_evaluation:
            parent_conditions = (
                AgentEvaluation.agent_evaluation_id == evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.delete_flag == 'N',
                AgentEvaluation.status == EvalRunStatus.RUNNING,
            )
            case_conditions = [
                AgentEvaluationCase.agent_evaluation_id == evaluation_id,
                AgentEvaluationCase.tenant_id == tenant_id,
                AgentEvaluationCase.delete_flag == 'N',
                AgentEvaluationCase.status.in_(('PENDING', 'RUNNING')),
                exists(select(AgentEvaluation.agent_evaluation_id).where(*parent_conditions)),
            ]
            if case_id is not None:
                case_conditions.append(AgentEvaluationCase.agent_evaluation_case_id == case_id)
            updated = session.execute(update(AgentEvaluationCase).where(*case_conditions).values(
                status='FAILED', error_message='Runtime execution was interrupted.',
                updated_by=user_id, update_time=func.current_timestamp(),
            ))
            result['evaluation_cases'] = max(0, updated.rowcount or 0)
            if evaluation_batch:
                updated = session.execute(update(AgentEvaluation).where(*parent_conditions).values(
                    status=EvalRunStatus.FAILED, error_message='Runtime execution was interrupted.',
                    updated_by=user_id, update_time=func.current_timestamp(),
                ))
                result['agent_evaluations'] = max(0, updated.rowcount or 0)
        if automation_id and conversation:
            conditions = [
                AgentAutomationRun.run_id == automation_id, AgentAutomationRun.tenant_id == tenant_id,
                AgentAutomationRun.user_id == user_id, AgentAutomationRun.conversation_id == conversation,
                AgentAutomationRun.delete_flag == 'N',
            ]
            if task_id is not None:
                conditions.append(AgentAutomationRun.task_id == task_id)
            updated = session.execute(update(AgentAutomationRun).where(
                *conditions, AgentAutomationRun.status == 'RUNNING',
            ).values(status='TIMEOUT', error_code='AUTOMATION_LEASE_EXPIRED',
                     error_message='Runtime execution was interrupted.', finished_at=func.current_timestamp(),
                     updated_by=user_id, update_time=func.current_timestamp()))
            result['automation_runs'] = max(0, updated.rowcount or 0)
            if task_id is not None and isinstance(automation_lock_owner, str) and automation_lock_owner:
                updated = session.execute(update(AgentAutomationTask).where(
                    AgentAutomationTask.task_id == task_id, AgentAutomationTask.tenant_id == tenant_id,
                    AgentAutomationTask.user_id == user_id, AgentAutomationTask.conversation_id == conversation,
                    AgentAutomationTask.lock_owner == automation_lock_owner, AgentAutomationTask.delete_flag == 'N',
                    exists(select(AgentAutomationRun.run_id).where(*conditions)),
                ).values(lock_owner=None, lock_until=None, updated_by=user_id, update_time=func.current_timestamp()))
                result['automation_locks'] = max(0, updated.rowcount or 0)
    return result
