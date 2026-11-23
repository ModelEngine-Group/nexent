from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update

from database.agent_automation_db import (
    claim_due_tasks,
    create_run,
    create_task,
    recover_orphaned_runs,
    release_all_task_locks,
)
from database.client import get_db_session
from database.db_models import AgentAutomationRun, AgentAutomationTask


def _utcnow():
    return datetime.now(timezone.utc)


def _unique_bigint():
    return random.SystemRandom().randint(1, 2 ** 62)


@pytest.mark.case_id('REL-AUTO-58D118DDC12E94CA')
@pytest.mark.stage('D5')
def test_orphaned_run_recovery_and_scheduler_lock_release():
    token = uuid.uuid4().hex[:12]
    tenant_id = f'd5-rel-{token}'
    user_id = f'd5-user-{token}'
    conversation_id = _unique_bigint()
    agent_id = _unique_bigint()
    now = _utcnow()

    with get_db_session() as session:
        session.execute(text('SELECT 1'))

    task = create_task({
        'tenant_id': tenant_id,
        'user_id': user_id,
        'conversation_id': conversation_id,
        'agent_id': agent_id,
        'title': 'd5 reliability orphan run recovery',
        'instruction': 'test instruction',
        'status': 'ACTIVE',
        'source': 'AUTOMATION',
        'schedule_mode': 'RECURRING',
        'schedule_rule_type': 'INTERVAL',
        'schedule_config': {'interval_seconds': 3600},
        'timezone': 'UTC',
        'next_fire_at': now - timedelta(days=1),
        'timeout_seconds': 600,
        'overlap_policy': 'SKIP',
        'misfire_policy': 'FIRE',
        'fire_count': 0,
        'consecutive_failures': 0,
    }, user_id)
    task_id = int(task['task_id'])

    running_run = create_run({
        'task_id': task_id,
        'tenant_id': tenant_id,
        'user_id': user_id,
        'conversation_id': conversation_id,
        'scheduled_fire_at': now - timedelta(minutes=10),
        'trigger_type': 'SCHEDULED',
        'status': 'RUNNING',
    }, user_id)
    queued_run = create_run({
        'task_id': task_id,
        'tenant_id': tenant_id,
        'user_id': user_id,
        'conversation_id': conversation_id,
        'scheduled_fire_at': now + timedelta(days=1),
        'trigger_type': 'SCHEDULED',
        'status': 'QUEUED',
    }, user_id)

    lock_owner_prev = 'prev-instance'
    with get_db_session() as session:
        session.execute(
            update(AgentAutomationTask)
            .where(AgentAutomationTask.task_id == task_id)
            .values(lock_owner=lock_owner_prev, lock_until=now + timedelta(hours=1))
        )

    try:
        affected = recover_orphaned_runs()
        assert isinstance(affected, int) and affected >= 1

        with get_db_session() as session:
            running_status, running_error_code = session.execute(
                select(AgentAutomationRun.status, AgentAutomationRun.error_code).where(
                    AgentAutomationRun.run_id == int(running_run['run_id'])
                )
            ).one()
            queued_status = session.execute(
                select(AgentAutomationRun.status).where(
                    AgentAutomationRun.run_id == int(queued_run['run_id'])
                )
            ).scalar_one()
        assert running_status == 'TIMEOUT'
        assert running_error_code == 'AUTOMATION_LEASE_EXPIRED'
        assert queued_status == 'QUEUED'

        released = release_all_task_locks()
        assert isinstance(released, int) and released >= 1

        with get_db_session() as session:
            lock_owner, lock_until = session.execute(
                select(AgentAutomationTask.lock_owner, AgentAutomationTask.lock_until).where(
                    AgentAutomationTask.task_id == task_id
                )
            ).one()
        assert lock_owner is None
        assert lock_until is None

        new_instance_id = f'new-instance-{token}'
        claimed = claim_due_tasks(new_instance_id, 100, 60.0)
        claimed_task_ids = {int(row['task_id']) for row in claimed}
        assert task_id in claimed_task_ids

        with get_db_session() as session:
            claimed_lock_owner = session.execute(
                select(AgentAutomationTask.lock_owner).where(
                    AgentAutomationTask.task_id == task_id
                )
            ).scalar_one()
        assert claimed_lock_owner == new_instance_id

    finally:
        with get_db_session() as session:
            session.execute(
                text('DELETE FROM nexent.agent_automation_run_t WHERE task_id = :tid'),
                {'tid': task_id},
            )
            session.execute(
                text('DELETE FROM nexent.agent_automation_task_t WHERE task_id = :tid'),
                {'tid': task_id},
            )
